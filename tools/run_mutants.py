"""Run isolated baseline and fault cases with trusted app and pytest evidence."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler
from xml.etree import ElementTree as ET

from app.server import ACCEPT_INVALID, FAILED_SESSION, FAULTS, OPEN_SETTINGS, REJECT_VALID, WRONG_IDENTITY, run
from tools.behavior import REASONS
from tools.common import AC_IDS, ROOT, PipelineError, atomic_json, child_env, load_json

CASE_TIMEOUT = 60
TARGETS = {
    WRONG_IDENTITY: ("AC-1", {"success_identity", "current_identity", "settings_identity"}),
    REJECT_VALID: ("AC-2", {"login_status"}),
    ACCEPT_INVALID: ("AC-3", {"invalid_status"}),
    FAILED_SESSION: ("AC-3", {"unexpected_auth", "protected_redirect", "identity_visible"}),
    OPEN_SETTINGS: ("AC-3", {"protected_redirect", "identity_visible"}),
}


@dataclass
class ManagedApp:
    url: str
    process: subprocess.Popen
    counts: Counter


def request_status(url):
    # Explicitly bypass system proxies for the loopback-only services.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as response:
        with response:
            return response.code, json.load(response)


@contextmanager
def start_app(root=ROOT, fault=None):
    ready = Queue()
    counts = Counter()
    command = [sys.executable, "-m", "tools.run_mutants", "--serve-case", fault or "normal"]
    with subprocess.Popen(
        command, cwd=root, env=child_env(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    ) as process:
        def read_events():
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    if event["event"] == "ready":
                        ready.put(event["port"])
                    elif event["event"] == "fault" and event["fault"] in FAULTS:
                        counts[event["fault"]] += 1
                except (ValueError, KeyError, TypeError):
                    continue
            ready.put(None)

        reader = Thread(target=read_events, daemon=True)
        reader.start()
        try:
            try:
                port = ready.get(timeout=8)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise PipelineError("App failed to announce a listening port.")
                url = f"http://127.0.0.1:{port}"
                if request_status(url + "/health") != (200, {"ready": True}):
                    raise PipelineError("App health check failed.")
            except (Empty, OSError, ValueError, URLError) as exc:
                raise PipelineError("App startup or health check failed.") from exc
            yield ManagedApp(url, process, counts)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            reader.join(timeout=3)


def run_pytest(root, folder, *, url=None, ac=None):
    folder.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "pytest_bdd.plugin",
        "-p", "tools.pytest_evidence", "tests/steps", "--qa-evidence", str(folder),
    ]
    if url is None:
        command.append("--collect-only")
    else:
        command.extend(["--qa-base-url", url])
    if ac:
        command.extend(["--qa-ac", ac])
    env = child_env()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    details = {"command": command, "exit_code": None, "timed_out": False}
    try:
        result = subprocess.run(
            command, cwd=root, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=CASE_TIMEOUT, check=False,
        )
        details["exit_code"] = result.returncode
    except subprocess.TimeoutExpired:
        details["timed_out"] = True
    except OSError:
        pass
    try:
        evidence = load_json(folder / "execution.json")
    except PipelineError:
        evidence = {"bindings": [], "cases": {}, "error": "No pytest evidence was produced."}
    details.update(evidence)
    return details


def independent_contract(root):
    with start_app(root) as app:
        status, _ = request_status(app.url + "/api/user")
        passed = status == 401 and app.process.poll() is None
    return {"status": "passed" if passed else "failed", "http_status": status,
            "command": "GET /api/user without Authorization (isolated app)"}


def run_case(root, folder, *, fault=None):
    details = {"health_passed": False, "app_stayed_up": False, "fault_hits": 0, "cases": {}}
    try:
        with start_app(root, fault) as app:
            details["health_passed"] = True
            details.update(run_pytest(root, folder, url=app.url, ac=TARGETS[fault][0] if fault else None))
            details["app_stayed_up"] = app.process.poll() is None
        if fault:
            details["fault_hits"] = app.counts[fault]
        elif app.counts:
            details["app_stayed_up"] = False
    except (PipelineError, OSError):
        details["error"] = "App startup or case infrastructure failed."
    junit(folder / "junit.xml", folder.name, details)
    atomic_json(folder / "result.json", details)
    return details


def baseline_passed(result):
    return (
        result.get("health_passed") and result.get("app_stayed_up") and not result.get("error")
        and result.get("exit_code") == 0 and set(result["cases"]) == set(AC_IDS)
        and all(case["status"] == "passed" for case in result["cases"].values())
    )


def classify(fault, result):
    ac, reasons = TARGETS[fault]
    case = result["cases"].get(ac, {})
    status = case.get("status")
    code = case.get("reason", "")
    hits = result["fault_hits"]
    if not result["health_passed"] or not result["app_stayed_up"]:
        outcome, reason = "invalid", "The isolated app failed to start or stay up."
    elif result.get("timed_out"):
        outcome, reason = "inconclusive", "The targeted pytest execution timed out."
    elif result.get("error") or result.get("exit_code") not in (0, 1) or (
        set(result["cases"]) != {ac} or status not in ("passed", "behavior_failure", "ambiguous")
    ):
        outcome, reason = "invalid", "Collection, setup or test execution was invalid."
    elif not hits:
        outcome, reason = "not_exercised", "The faulty branch did not execute."
    elif status == "behavior_failure" and result["exit_code"] == 1 and code in reasons:
        outcome, reason = "killed", REASONS[code]
    elif status == "passed":
        outcome, reason = "survived", "The targeted scenario passed after the branch executed."
    elif status == "behavior_failure" and code in REASONS:
        outcome, reason = "survived", "The scenario failed a different behavior check."
    else:
        outcome, reason = "inconclusive", "No attributable behavioral failure was verified."
    return {
        "fault": fault, "ac": ac, "outcome": outcome, "fault_hits": hits,
        "health_passed": result["health_passed"], "reason": reason, "pytest_exit_code": result.get("exit_code"),
        "step_line": case.get("step_line"), "command": result.get("command"),
    }


def junit(path, name, result):
    # Build JUnit from trusted fields. Pytest's default XML can include
    # assertion operands, exception reprs, captured output and credentials.
    cases = result.get("cases", {}) or {"infrastructure": {"status": "invalid", "reason": "No case executed."}}
    failures = sum(case["status"] in ("behavior_failure", "ambiguous") for case in cases.values())
    errors = sum(case["status"] in ("invalid", "unexecuted") for case in cases.values())
    suite = ET.Element("testsuite", name=name, tests=str(len(cases)), failures=str(failures), errors=str(errors))
    for ac, case in sorted(cases.items()):
        testcase = ET.SubElement(suite, "testcase", name=ac, classname="seed1")
        status = case["status"]
        if status != "passed":
            element = "failure" if status in ("behavior_failure", "ambiguous") else "error"
            reason = REASONS.get(case.get("reason"), case.get("reason", "Case did not complete."))
            ET.SubElement(testcase, element, message=reason)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def execute_verification(root, folder):
    result = {"baselines": [], "mutants": [], "api": {"status": "not_run"}, "failure": None}
    collection = run_pytest(root, folder / "collection")
    result["collection"] = collection
    if collection["exit_code"] != 0 or collection["error"] or not collection["bindings"]:
        result["failure"] = collection["error"] or "Generated scenario collection failed."
        return result

    for name in ("baseline-a", "baseline-b"):
        baseline = run_case(root, folder / name)
        result["baselines"].append({"name": name, "passed": bool(baseline_passed(baseline)), **baseline})
    try:
        result["api"] = independent_contract(root)
    except (PipelineError, OSError, ValueError):
        result["api"] = {"status": "invalid"}
    if not all(baseline["passed"] for baseline in result["baselines"]) or result["api"]["status"] != "passed":
        result["failure"] = "Baseline or independent API 401 verification failed. Mutants were not run."
        return result

    for fault in FAULTS:
        case = run_case(root, folder / "mutants" / fault, fault=fault)
        result["mutants"].append(classify(fault, case))
    if not all(mutant["outcome"] == "killed" for mutant in result["mutants"]):
        result["failure"] = "Five verified mutant kills are required."
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--serve-case" or sys.argv[2] not in ("normal", *FAULTS):
        raise SystemExit("Run verification through tools/pipeline.py.")
    selected = sys.argv[2]
    run(0, fault=None if selected == "normal" else selected, emit=lambda event: print(json.dumps(event), flush=True))
