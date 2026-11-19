"""Trusted app, validation and reporting checks. No generated feature is needed."""

from dataclasses import replace
import json
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from zipfile import ZipFile

import pytest

from app.server import (
    ACCEPT_INVALID, BASELINE, FAILED_SESSION, FAULTS, INVALID_PASSWORD, OPEN_SETTINGS,
    REJECT_VALID, TOKEN_PREFIX, WRONG_IDENTITY,
)
from tools import pipeline, run_mutants
from tools.behavior import locator, storage_presence
from tools.common import AC_IDS, FEATURE, RECEIPT, ROOT, PipelineError, digest, git
from tools.playwright_trace import trace_events
from tools.validate_scope import check_scope, generated_hashes
from tools.validate_traceability import approved_feature, feature_structure, lint_generated


def api(url, path, user=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Token {token}"
    data = json.dumps({"user": user}).encode() if user is not None else None
    request = Request(url + path, data=data, headers=headers)
    opener = build_opener(ProxyHandler({}))
    try:
        response = opener.open(request, timeout=3)
    except HTTPError as failure:
        response = failure
    with response:
        return response.code, json.load(response)


def credentials(identity):
    return {"email": identity.email, "password": identity.password}


def registration(identity):
    return {"username": identity.username, **credentials(identity)}


def assert_user(status, body, expected_status, identity):
    assert (status, set(body)) == (expected_status, {"user"})
    user = body["user"]
    assert set(user) == {"username", "email", "token"}
    assert (user["username"], user["email"]) == (identity.username, identity.email)
    assert user["token"].startswith(TOKEN_PREFIX)
    return user["token"]


def test_api_contract_and_fresh_state(registration_user):
    with run_mutants.start_app() as app:
        assert api(app.url, "/api/user") == (401, {"errors": {"authentication": ["is required"]}})
        assert api(app.url, "/api/users/login", {"email": BASELINE.email})[0] == 400
        status, body = api(app.url, "/api/users", registration(registration_user))
        register_token = assert_user(status, body, 201, registration_user)
        status, body = api(app.url, "/api/users/login", credentials(BASELINE))
        baseline_token = assert_user(status, body, 200, BASELINE)
        for token, identity in ((register_token, registration_user), (baseline_token, BASELINE)):
            status, body = api(app.url, "/api/user", token=token)
            assert_user(status, body, 200, identity)
        invalid = replace(BASELINE, password=INVALID_PASSWORD)
        assert api(app.url, "/api/users/login", credentials(invalid)) == (
            422, {"errors": {"email or password": ["is invalid"]}},
        )
    assert not app.counts
    with run_mutants.start_app() as fresh:
        assert api(fresh.url, "/api/user", token=baseline_token)[0] == 401
        assert api(fresh.url, "/api/users/login", credentials(registration_user))[0] == 422
        assert api(fresh.url, "/api/users/login", credentials(BASELINE))[0] == 200


def submit(page, route, identity):
    group = "register" if route == "/register" else "login"
    page.goto(route)
    if group == "register":
        locator(page, "register.username").fill(identity.username)
    locator(page, group + ".email").fill(identity.email)
    locator(page, group + ".password").fill(identity.password)
    locator(page, group + ".submit").click()


def test_chromium_contract(browser, registration_user):
    with run_mutants.start_app() as app:
        for route, identity in (("/register", registration_user), ("/login", BASELINE)):
            context = browser.new_context(base_url=app.url)
            try:
                page = context.new_page()
                page.goto("/login")
                assert not context.cookies() and not any(storage_presence(page).values())
                endpoint = "/api/users" if route == "/register" else "/api/users/login"
                with page.expect_response(lambda value: value.url.endswith(endpoint)) as submitted:
                    submit(page, route, identity)
                page.wait_for_url("**/settings")
                # Chromium must still expose the original API envelope at settings.
                assert submitted.value.json()["user"]["email"] == identity.email
                assert locator(page, "account.identity").inner_text(timeout=3000) == identity.email
                assert storage_presence(page)["jwt_present"]
                assert not context.cookies()
            finally:
                context.close()
        context = browser.new_context(base_url=app.url)
        try:
            page = context.new_page()
            with page.expect_response(lambda value: value.url.endswith("/api/users/login")) as rejected:
                submit(page, "/login", replace(BASELINE, password=INVALID_PASSWORD))
            assert rejected.value.json() == {"errors": {"email or password": ["is invalid"]}}
            assert locator(page, "login.error").inner_text(timeout=3000) == "Email or password is invalid."
            assert not context.cookies() and not any(storage_presence(page).values())
            page.goto("/settings")
            page.wait_for_url("**/login")
            assert locator(page, "login.heading").is_visible()
            assert locator(page, "account.identity").count() == 0
        finally:
            context.close()


@pytest.mark.parametrize("fault", FAULTS)
def test_fault_branches_are_targeted(fault, browser, registration_user):
    with run_mutants.start_app(fault=fault) as app:
        assert api(app.url, "/health") == (200, {"ready": True})
        assert api(app.url, "/api/user")[0] == 401
        assert not app.counts
        invalid = replace(BASELINE, password=INVALID_PASSWORD)
        if fault == WRONG_IDENTITY:
            assert api(app.url, "/api/users/login", credentials(BASELINE))[0] == 200
            assert not app.counts
            status, body = api(app.url, "/api/users", registration(registration_user))
            assert (status, body["user"]["email"]) == (201, BASELINE.email)
        elif fault == REJECT_VALID:
            assert api(app.url, "/api/users/login", credentials(invalid))[0] == 422
            assert not app.counts
            assert api(app.url, "/api/users/login", credentials(BASELINE))[0] == 422
        elif fault == ACCEPT_INVALID:
            assert api(app.url, "/api/users/login", credentials(BASELINE))[0] == 200
            assert not app.counts
            assert api(app.url, "/api/users/login", credentials(invalid))[0] == 200
        else:
            context = browser.new_context(base_url=app.url)
            try:
                page = context.new_page()
                page.set_default_timeout(3000)
                if fault == FAILED_SESSION:
                    assert api(app.url, "/api/users/login", credentials(BASELINE))[0] == 200
                    assert not app.counts
                    submit(page, "/login", invalid)
                    assert locator(page, "login.error").inner_text() == "Email or password is invalid."
                    assert storage_presence(page)["jwt_present"]
                else:
                    assert not app.counts
                page.goto("/settings")
                assert locator(page, "account.identity").inner_text() == BASELINE.email
            finally:
                context.close()
    assert app.counts == {fault: 1}


def gherkin_stub():
    # Parser grammar fixture with placeholder steps, not a semantic login feature.
    parts = ["@SEED-1\nFeature: Parser probe\n  Background:\n    Given parser setup\n"]
    for index, ac in enumerate(AC_IDS, 1):
        parts.append(f"  @{ac}\n  Scenario: Probe {index}\n    When action {index}\n    Then check {index}\n")
    return "\n".join(parts)


def test_parser_maps_exactly_three_scenarios_with_background():
    found = feature_structure(gherkin_stub().encode())
    for index, ac in enumerate(AC_IDS, 1):
        assert found[ac]["title"] == f"Probe {index}"
        assert [step["kind"] for step in found[ac]["steps"]] == ["given", "when", "then"]


@pytest.mark.parametrize(("before", "after"), [
    ("@AC-2", "@AC-1"),
    ("@AC-2", ""),
    ("@AC-3", "@AC-9"),
    ("@AC-3", "@AC-3 @AC-3"),
    ("    When action 2", "    When "),
    ("    Then check 2", "    Wrong step syntax"),
    ("  Background:", "  Backgroud:"),
    ("@SEED-1", "@SEED-1 @SEED-1"),
    ("  Scenario: Probe 3", "  Scenario Outline: Probe 3"),
])
def test_parser_rejects_bad_structure(before, after):
    with pytest.raises(PipelineError):
        feature_structure(gherkin_stub().replace(before, after).encode())


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


@pytest.fixture
def git_case(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.test")
    git(tmp_path, "config", "user.name", "Temporary infrastructure fixture")
    git(tmp_path, "config", "commit.gpgsign", "false")
    put(tmp_path, "app/server.py", "# scope fixture\n")
    put(tmp_path, ".gitignore", "/reports/\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Trusted base fixture")
    git(tmp_path, "switch", "-c", "demo-fixture")
    return tmp_path


@pytest.fixture
def approved_case(git_case):
    draft = gherkin_stub()
    put(git_case, FEATURE, draft)
    put(git_case, RECEIPT, digest(draft.encode()) + "\n")
    git(git_case, "add", FEATURE, RECEIPT)
    git(git_case, "commit", "-m", "Gate fixture in disposable repository")
    return git_case


def test_requires_approval_and_detects_post_gate_edits(git_case, approved_case):
    feature = git_case / FEATURE
    receipt = git_case / RECEIPT
    saved = receipt.read_text()
    receipt.unlink()
    with pytest.raises(PipelineError, match="Missing"):
        approved_feature(git_case)
    receipt.write_text("0" * 64 + "\n")
    with pytest.raises(PipelineError, match="does not match"):
        approved_feature(git_case)
    receipt.write_text(saved)
    assert approved_feature(approved_case)[0] == saved.strip()
    feature.write_text(feature.read_text() + "\n# changed\n")
    with pytest.raises(PipelineError, match="does not match"):
        approved_feature(git_case)
    receipt.write_text(digest(feature.read_bytes()) + "\n")
    with pytest.raises(PipelineError, match="byte-identical"):
        check_scope(git_case, "main")
    git(git_case, "add", FEATURE, RECEIPT)
    git(git_case, "commit", "-m", "Illicit receipt rewrite")
    with pytest.raises(PipelineError, match="stay unchanged"):
        check_scope(git_case, "main")


def test_gate_rejects_noninteractive():
    result = subprocess.run(
        [sys.executable, "tools/pipeline.py", "approve-gherkin", "SEED-1"],
        cwd=ROOT, input="APPROVE\n", text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert "interactive terminal" in result.stderr


def test_scope_accepts_generated_additions_and_rejects_protected_staged_changes(approved_case):
    put(approved_case, "tests/steps/test_probe.py", "# new steps\n")
    put(approved_case, "tests/pages/probe.py", "# new page\n")
    check_scope(approved_case, "main")
    path = approved_case / "app/server.py"
    old = path.read_text()
    path.write_text("# staged unauthorized edit\n")
    git(approved_case, "add", "app/server.py")
    path.write_text(old)
    with pytest.raises(PipelineError, match="Disallowed change"):
        check_scope(approved_case, "main")


@pytest.mark.parametrize("name", ["app/other.py", "tools/probe.py", "contracts/probe.json", "tests/steps/conftest.py"])
def test_scope_rejects_untracked_protected_paths(approved_case, name):
    put(approved_case, name, "# new\n")
    with pytest.raises(PipelineError, match="Disallowed untracked"):
        check_scope(approved_case, "main")


def test_frozen_bytes_are_checked_even_when_git_hides_the_edit(approved_case):
    git(approved_case, "update-index", "--assume-unchanged", "app/server.py")
    put(approved_case, "app/server.py", "# hidden local edit\n")
    with pytest.raises(PipelineError, match="frozen file"):
        check_scope(approved_case, "main")


def test_scope_rejects_renames_and_symlinks(approved_case):
    target = approved_case / "tests/pages/link.py"
    target.parent.mkdir(parents=True)
    target.symlink_to(approved_case / "app/server.py")
    with pytest.raises(PipelineError, match="Symlink"):
        check_scope(approved_case, "main")
    git(approved_case, "add", "tests/pages/link.py")
    with pytest.raises(PipelineError, match="regular nonexecutable"):
        check_scope(approved_case, "main")
    git(approved_case, "reset", "--", "tests/pages/link.py")
    target.unlink()
    git(approved_case, "mv", "app/server.py", "tests/pages/server.py")
    with pytest.raises(PipelineError, match="Disallowed change"):
        check_scope(approved_case, "main")


@pytest.mark.parametrize("source", [
    "assert True", "assert False", "pytest.skip()", "pytest.mark.xfail", "page.wait_for_timeout(10)",
    "page.route('**/*', stub)", "import os", "from app.server import BASELINE", "page.evaluate('localStorage.clear()')",
    "try:\n    assert condition\nexcept AssertionError:\n    pass",
])
def test_generated_lint_rejects_shortcuts(approved_case, source):
    put(approved_case, "tests/steps/test_probe.py", source + "\n")
    put(approved_case, "tests/pages/probe.py", "class Probe:\n    pass\n")
    with pytest.raises(PipelineError, match="Restricted|Forbidden"):
        lint_generated(approved_case, generated_hashes(approved_case))


@pytest.mark.parametrize(("changes", "case", "outcome"), [
    ({}, {"status": "behavior_failure", "reason": "login_status"}, "killed"),
    ({"exit_code": 0}, {"status": "passed"}, "survived"),
    ({}, {"status": "behavior_failure", "reason": "settings_identity"}, "survived"),
    ({"fault_hits": 0}, {"status": "behavior_failure", "reason": "login_status"}, "not_exercised"),
    ({"health_passed": False}, {}, "invalid"),
    ({}, {"status": "invalid"}, "invalid"),
    ({"timed_out": True}, {}, "inconclusive"),
    ({}, {"status": "ambiguous"}, "inconclusive"),
])
def test_mutant_evidence_classification(changes, case, outcome):
    data = {
        "health_passed": True, "app_stayed_up": True, "exit_code": 1, "fault_hits": 1,
        "cases": {"AC-2": case}, **changes,
    }
    assert run_mutants.classify(REJECT_VALID, data)["outcome"] == outcome


def test_baseline_failure_blocks_all_mutants(monkeypatch, tmp_path):
    executed = []

    def case(root, folder, *, fault=None):
        executed.append((folder.name, fault))
        return {
            "health_passed": True, "app_stayed_up": True, "exit_code": int(folder.name == "baseline-a"),
            "cases": {ac: {"status": "passed"} for ac in AC_IDS},
        }

    monkeypatch.setattr(run_mutants, "run_pytest", lambda *args: {
        "exit_code": 0, "error": None, "bindings": [{"ac": "AC-1"}],
    })
    monkeypatch.setattr(run_mutants, "run_case", case)
    monkeypatch.setattr(run_mutants, "independent_contract", lambda root: {"status": "passed"})
    result = run_mutants.execute_verification(tmp_path, tmp_path)
    assert executed == [("baseline-a", None), ("baseline-b", None)]
    assert [row["passed"] for row in result["baselines"]] == [False, True]
    assert not result["mutants"] and result["failure"]


def test_repairs_bounded_and_feature_immutable(approved_case):
    root = approved_case
    path = put(root, "tests/steps/test_probe.py", "# initial generated fixture\n")
    put(root, "tests/pages/probe.py", "# page fixture\n")
    sha, _ = approved_feature(root)
    (root / "reports").mkdir()
    session = {
        "base": "main", "repairs": [], "pending": None,
        "last": {"passed": False, "files": generated_hashes(root), "feature_sha256": sha, "report_dir": "original"},
    }
    for attempt in (1, 2):
        pipeline.start_repair(root, session, "Infrastructure test reason")
        with pytest.raises(PipelineError, match="no generated code changes"):
            pipeline.verification(root, "main", session=session)
        path.write_text(f"# edited generated fixture {attempt}\n")
        name = f"results-{attempt}"
        (root / "reports" / name).mkdir()
        files = generated_hashes(root)
        pipeline.finish_repair(root, session, {"passed": False, "files": files, "report_dir": name})
        assert session["repairs"][-1]["changed_files"] == ["tests/steps/test_probe.py"]
        assert "edited generated fixture" in (root / "reports" / name / f"repair-{attempt}.diff").read_text()
        session["last"].update(files=files, report_dir=name)
        assert approved_feature(root)[0] == sha
    with pytest.raises(PipelineError, match="exhausted"):
        pipeline.start_repair(root, session, "Third attempt")
    put(root, "app/server.py", "# unauthorized change\n")
    with pytest.raises(PipelineError, match="Disallowed change"):
        pipeline.verification(root, "main", session=session)


def test_evidence_formats_do_not_serialize_raw_values(tmp_path):
    private = "qa.jwt.example-secret-value"
    password = "sample-private-password"
    archive_path = tmp_path / "raw.zip"
    with ZipFile(archive_path, "w") as archive:
        trace = [
            {"type": "before", "callId": "call@1", "apiName": "locator.fill",
             "params": {"value": password}, "startTime": 12},
            {"type": "after", "callId": "call@1", "endTime": 15, "error": {"message": private}},
            {"type": "network", "request": {"header": "Authorization: Token " + private}},
        ]
        archive.writestr("trace.trace", "\n".join(json.dumps(event) for event in trace))
    events = trace_events(archive_path)
    assert events == [
        {"phase": "before", "id": "call@1", "api": "locator.fill", "monotonic_ms": 12},
        {"phase": "after", "id": "call@1", "monotonic_ms": 15, "failed": True},
    ]
    assert private not in json.dumps(events) and password not in json.dumps(events)
    result = {"cases": {"AC-2": {"status": "behavior_failure", "reason": "login_status", "raw": private}}}
    target = tmp_path / "junit.xml"
    run_mutants.junit(target, "baseline", result)
    assert "Valid login returned the wrong HTTP status." in target.read_text()
    assert private not in target.read_text()
