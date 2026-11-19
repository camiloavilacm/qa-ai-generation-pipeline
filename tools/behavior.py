"""Trusted Playwright observations for generated Then steps."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.server import CHECKS, CONTRACT, UI

SELECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts/selectors.json").read_text()
)["selectors"]
AUTH = CONTRACT["authentication"]
REGISTER = CONTRACT["api_prefix"] + CHECKS["register"]["path"]
LOGIN = CONTRACT["api_prefix"] + CHECKS["login"]["path"]
CURRENT = CONTRACT["api_prefix"] + CHECKS["current_user"]["path"]

POSITIVE = {"success_response", "authenticated", "settings_identity"}
REQUIRED_CHECKS = {
    "AC-1": POSITIVE,
    "AC-2": POSITIVE,
    "AC-3": {"invalid_response", "invalid_message", "no_auth", "protected_redirect", "identity_absent"},
}

# Only these stable identifiers can appear as a behavioral failure in evidence.
REASONS = {
    "register_status": "Registration returned the wrong HTTP status.",
    "login_status": "Valid login returned the wrong HTTP status.",
    "success_identity": "The response user differed from the expected identity.",
    "success_token": "The successful response did not contain an authentication token.",
    "browser_auth": "The browser did not retain the issued authentication token.",
    "current_status": "The browser session did not authenticate the current-user request.",
    "current_identity": "The current user differed from the expected identity.",
    "settings_identity": "Settings displayed a different identity.",
    "invalid_status": "Invalid credentials returned the wrong HTTP status.",
    "invalid_body": "Invalid credentials returned the wrong API error.",
    "invalid_message": "The alert text differed from the required error.",
    "unexpected_auth": "The rejected browser session contained authentication state.",
    "protected_redirect": "Direct settings navigation exposed an authenticated view instead of redirecting.",
    "identity_visible": "The protected identity was visible after a denied navigation.",
}


class BehaviorMismatch(AssertionError):
    def __init__(self, code):
        self.code = code
        super().__init__(REASONS[code])


class ObservationError(Exception):
    """The intended interaction was not observed with enough certainty."""


def require(condition, code):
    if not condition:
        raise BehaviorMismatch(code)


def locator(page, name):
    spec = SELECTORS[name]
    match spec["by"]:
        case "role":
            kwargs = {"name": spec["name"], "exact": True} if "name" in spec else {}
            return page.get_by_role(spec["value"], **kwargs)
        case "label":
            return page.get_by_label(spec["value"], exact=True)
        case "data-testid":
            return page.get_by_test_id(spec["value"])
    raise ValueError("Unsupported selector kind")


def storage_presence(page):
    return page.evaluate(
        """key => ({
          local_present: localStorage.length > 0,
          session_present: sessionStorage.length > 0,
          jwt_present: Boolean(localStorage.getItem(key))
        })""",
        AUTH["storage_key"],
    )


@dataclass
class Observation:
    page: object
    base_url: str
    ac: str
    identity: object
    checks: set = field(default_factory=set)
    responses: list = field(default_factory=list)
    navigations: list = field(default_factory=list)
    step_kind: str | None = None

    def __post_init__(self):
        self.page.on("response", self.on_response)
        self.page.on("request", self.on_request)

    def on_response(self, response):
        if (
            response.request.method == "POST"
            and response.url in {self.base_url + REGISTER, self.base_url + LOGIN}
        ):
            self.responses.append(response)

    def on_request(self, request):
        if request.is_navigation_request() and request.url == self.base_url + UI["protected_route"]:
            self.navigations.append(len(self.responses))

    def call(self, name):
        if self.step_kind != "then" or name not in REQUIRED_CHECKS[self.ac]:
            raise ObservationError("Call checks from a matching Then step.")
        if name in self.checks:
            raise ObservationError("Each behavior check must run once per scenario.")
        getattr(self, name)()
        self.checks.add(name)

    def response(self):
        endpoint = REGISTER if self.ac == "AC-1" else LOGIN
        if len(self.responses) != 1 or self.responses[0].url != self.base_url + endpoint:
            raise ObservationError("Expected one observed submission to the scenario's auth endpoint.")
        response = self.responses[0]
        user = (response.request.post_data_json or {}).get("user", {})
        if user.get("email") != self.identity.email or user.get("password") != self.identity.password:
            raise ObservationError("The browser submitted different credentials from the scenario fixture.")
        if self.ac == "AC-1" and user.get("username") != self.identity.username:
            raise ObservationError("The browser submitted a different registration name.")
        return response

    def success_response(self):
        response = self.response()
        operation = "register" if self.ac == "AC-1" else "login"
        require(response.status == CHECKS[operation]["status"], f"{operation}_status")
        body = response.json()
        user = body.get("user", {}) if isinstance(body, dict) else {}
        if not isinstance(user, dict):
            user = {}
        require(
            user.get("email") == self.identity.email and user.get("username") == self.identity.username,
            "success_identity",
        )
        require(isinstance(user.get("token"), str) and bool(user["token"]), "success_token")

    def authenticated(self):
        self.page.wait_for_url(self.base_url + UI["protected_route"])
        expected = self.response().json()["user"]["token"]
        token = self.page.evaluate("key => localStorage.getItem(key)", AUTH["storage_key"])
        require(bool(token) and token == expected, "browser_auth")
        response = self.page.request.get(
            self.base_url + CURRENT,
            headers={AUTH["header"]: f"{AUTH['scheme']} {token}"},
            timeout=3000,
        )
        try:
            require(response.status == CHECKS["current_user"]["status"], "current_status")
            user = response.json().get("user", {})
            require(
                user.get("email") == self.identity.email and user.get("username") == self.identity.username,
                "current_identity",
            )
        finally:
            response.dispose()

    def settings_identity(self):
        self.page.wait_for_url(self.base_url + UI["protected_route"])
        actual = locator(self.page, "account.identity").inner_text()
        require(actual == self.identity.email, "settings_identity")

    def invalid_response(self):
        response = self.response()
        expected = CHECKS["invalid_login"]
        require(response.status == expected["status"], "invalid_status")
        require(response.json() == expected["body"], "invalid_body")

    def invalid_message(self):
        message = locator(self.page, "login.error")
        message.wait_for(state="visible")
        require(message.inner_text() == UI["invalid_login_message"], "invalid_message")

    def no_auth(self):
        self.invalid_message()
        state = storage_presence(self.page)
        require(not any(state.values()) and not self.page.context.cookies(), "unexpected_auth")

    def protected_redirect(self):
        self.check_direct_settings_request()
        heading = locator(self.page, "login.heading")
        identity = locator(self.page, "account.identity")
        # Wait for an observable outcome. Missing locators/timeouts do not prove
        # that the wrong route was served.
        heading.or_(identity).first.wait_for(state="visible")
        route = urlsplit(self.page.url).path
        if route == UI["protected_route"] and identity.is_visible():
            raise BehaviorMismatch("protected_redirect")
        if route != UI["unauthenticated_redirect"] or not heading.is_visible():
            raise ObservationError("The settings navigation had no recognized terminal view.")

    def identity_absent(self):
        self.check_direct_settings_request()
        require(locator(self.page, "account.identity").count() == 0, "identity_visible")

    def check_direct_settings_request(self):
        if not self.navigations or not self.navigations[-1]:
            raise ObservationError("Direct settings navigation after login was not observed.")
