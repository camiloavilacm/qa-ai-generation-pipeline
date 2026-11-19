"""Local synthetic login app. The runner enables at most one test-only mutation."""

import argparse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "contracts/api-expectations.json").read_text())
UI = CONTRACT["ui"]
ENVELOPES = json.loads((ROOT / "contracts/envelopes.json").read_text())
CHECKS = CONTRACT["checks"]

WRONG_IDENTITY = "BUG_WRONG_REGISTRATION_IDENTITY"
REJECT_VALID = "BUG_REJECT_VALID_LOGIN"
ACCEPT_INVALID = "BUG_ACCEPT_ANY_PASSWORD"
FAILED_SESSION = "BUG_SESSION_ON_FAILED_LOGIN"
OPEN_SETTINGS = "BUG_PROTECTED_ROUTE_OPEN"
FAULTS = (WRONG_IDENTITY, REJECT_VALID, ACCEPT_INVALID, FAILED_SESSION, OPEN_SETTINGS)


@dataclass(frozen=True)
class Identity:
    username: str
    email: str
    password: str = field(repr=False)


BASELINE = Identity("baseline", "baseline@example.test", "baseline-fixture-password")
INVALID_PASSWORD = "invalid-fixture-password"
TOKEN_PREFIX = "qa.jwt."


class AppState:
    def __init__(self, fault=None, emit=None):
        self.fault = fault
        self.emit = emit
        self.users = {BASELINE.email: BASELINE}
        self.sessions = {}
        self.lock = threading.Lock()

    def hit(self, fault):
        if self.fault != fault:
            return False
        self.emit({"event": "fault", "fault": fault})
        return True

    def issue(self, identity):
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.sessions[token] = identity
        return self.user_response(identity, token)

    @staticmethod
    def user_response(identity, token):
        return {"user": {"username": identity.username, "email": identity.email, "token": token}}

    def authenticate(self, authorization):
        prefix = CONTRACT["authentication"]["scheme"] + " "
        if authorization.startswith(prefix):
            token = authorization[len(prefix):]
            return self.sessions.get(token), token
        return None, ""


FORMS = {
    "/register": ("Sign up", '<label>Username <input name="username" required></label>'),
    "/login": ("Sign in", ""),
}


def document(route):
    if route == "/settings":
        body = "<h1>Settings</h1><main></main>"
    else:
        heading, username = FORMS[route]
        body = f"""
          <h1>{heading}</h1>
          <form>
            {username}
            <label>Email <input type="email" name="email" required></label>
            <label>Password <input type="password" name="password" required></label>
            <button type="submit">{heading}</button>
          </form>
          <p role="alert" hidden></p>
        """
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>QA login demo</title>
{body}
<script type="module" src="/browser.js"></script>
</html>""".encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep HTTP requests and headers out of the test evidence.
        pass

    @property
    def state(self):
        return self.server.state

    def respond(self, status, body, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, body, headers=None):
        self.respond(status, json.dumps(body).encode(), "application/json", headers)

    def do_GET(self):
        if self.path == "/health":
            with self.state.lock:
                seeded = self.state.users.get(BASELINE.email) == BASELINE
            self.json(200 if seeded else 503, {"ready": seeded})
        elif self.path in (*FORMS, "/settings"):
            self.respond(200, document(self.path), "text/html; charset=utf-8")
        elif self.path == "/browser.js":
            self.respond(200, (ROOT / "app/browser.js").read_bytes(), "text/javascript")
        elif self.path == "/api/user":
            with self.state.lock:
                identity, token = self.state.authenticate(self.headers.get("Authorization", ""))
                if identity is None:
                    self.json(401, ENVELOPES["unauthenticated_response"])
                else:
                    self.json(200, self.state.user_response(identity, token))
        elif self.path == "/settings/access":
            # This is the settings UI's access check. The API contract stays independent.
            with self.state.lock:
                identity, _ = self.state.authenticate(self.headers.get("Authorization", ""))
                if identity is None and self.state.hit(OPEN_SETTINGS):
                    identity = BASELINE
                if identity is None:
                    self.json(401, ENVELOPES["unauthenticated_response"])
                else:
                    self.json(200, {"email": identity.email})
        else:
            self.json(404, {"error": "Not found"})

    def read_user(self, fields):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 8192:
            raise ValueError("Invalid request size")
        user = json.loads(self.rfile.read(size))["user"]
        if not isinstance(user, dict) or any(not isinstance(user.get(key), str) or not user[key] for key in fields):
            raise ValueError("Invalid user envelope")
        return {key: user[key] for key in fields}

    def do_POST(self):
        register = self.path == "/api/users"
        if not register and self.path != "/api/users/login":
            self.json(404, {"error": "Not found"})
            return
        fields = ("username", "email", "password") if register else ("email", "password")
        try:
            user = self.read_user(fields)
        except (ValueError, TypeError, KeyError):
            self.json(400, {"errors": {"user": ["is invalid"]}})
            return
        with self.state.lock:
            if register:
                self.register(user)
            else:
                self.login(user)

    def register(self, user):
        identity = Identity(**user)
        if identity.email in self.state.users:
            self.json(422, {"errors": {"email": ["has already been taken"]}})
            return
        self.state.users[identity.email] = identity
        if self.state.hit(WRONG_IDENTITY):
            identity = BASELINE
        self.json(201, self.state.issue(identity))

    def login(self, user):
        identity = self.state.users.get(user["email"])
        valid = identity is not None and identity.password == user["password"]
        if identity == BASELINE and valid and self.state.hit(REJECT_VALID):
            valid = False
        elif identity == BASELINE and not valid and self.state.hit(ACCEPT_INVALID):
            valid = True
        if valid:
            self.json(200, self.state.issue(identity))
            return
        headers = None
        if identity == BASELINE and self.state.hit(FAILED_SESSION):
            session = self.state.issue(identity)
            headers = {"X-QA-Session": session["user"]["token"]}
        self.json(422, CHECKS["invalid_login"]["body"], headers)


def run(port=8000, *, fault=None, emit=None):
    if fault is not None and (fault not in FAULTS or emit is None):
        raise ValueError("Fault injection requires a trusted runner event stream")
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        server.state = AppState(fault, emit)
        if emit is not None:
            emit({"event": "ready", "port": server.server_port})
        else:
            print(f"QA login app at http://127.0.0.1:{server.server_port}/login", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    run(parser.parse_args().port)
