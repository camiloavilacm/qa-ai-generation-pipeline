"""Collect real pytest-bdd bindings and emit redacted case outcomes."""

from pathlib import Path

import pytest
from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout
from pytest_bdd.scenario import find_fixturedefs_for_step

from tools.behavior import BehaviorMismatch, ObservationError, REQUIRED_CHECKS
from tools.common import AC_IDS, FEATURE, ROOT, PipelineError, atomic_json
from tools.validate_scope import is_generated
from tools.validate_traceability import approved_feature, check_bindings


def pytest_addoption(parser):
    group = parser.getgroup("SEED-1 verification")
    group.addoption("--qa-evidence", default="")
    group.addoption("--qa-base-url", default="")
    group.addoption("--qa-ac", choices=AC_IDS)


def pytest_configure(config):
    config._qa_evidence = {"bindings": [], "cases": {}, "error": None}
    if config.getoption("--qa-evidence") and not config.getoption("--qa-base-url") and not config.option.collectonly:
        raise pytest.UsageError("A managed app URL is required for scenario execution.")


def bind(item, fixture_manager):
    # pytest-bdd 8.1 is pinned because these collection interfaces are internal.
    template = getattr(item.obj, "__scenario__", None)
    if not template or Path(template.feature.filename).resolve() != ROOT / FEATURE:
        raise PipelineError("Every collected test must bind the approved login feature.")
    marks = {mark.name for mark in item.iter_markers()}
    tags = set(AC_IDS) & marks
    if tags != template.tags or len(tags) != 1 or "SEED-1" not in marks:
        raise PipelineError("Collected pytest markers do not match the approved scenario.")
    if marks & {"skip", "skipif", "xfail", "parametrize"}:
        raise PipelineError("Generated tests may not skip, xfail or parameterize the scenarios.")
    steps = []
    for step in template.render({}).steps:
        providers = list(find_fixturedefs_for_step(step, fixture_manager, item))
        if len(providers) != 1:
            raise PipelineError(f"Expected one binding for feature line {step.line_number}; found {len(providers)}.")
        function = providers[0].func._pytest_bdd_step_context.step_func
        path = Path(function.__code__.co_filename).resolve().relative_to(ROOT).as_posix()
        if not is_generated(path) or not path.startswith("tests/steps/"):
            raise PipelineError(f"Feature line {step.line_number} must bind a generated step function.")
        steps.append({"line": step.line_number, "function": f"{path}:{function.__name__}"})
    ac = next(iter(tags))
    item._qa_ac = ac
    item._qa_result = {"status": "unexecuted", "checks": []}
    return {"ac": ac, "title": template.name, "steps": steps}


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    if not config.getoption("--qa-evidence"):
        return
    try:
        _, structure = approved_feature(ROOT)
        bindings = [bind(item, session._fixturemanager) for item in items]
        check_bindings(structure, bindings)
    except (PipelineError, ValueError) as exc:
        config._qa_evidence["error"] = str(exc) if isinstance(exc, PipelineError) else "Step source is outside the repository."
        raise pytest.UsageError(config._qa_evidence["error"]) from None
    config._qa_evidence["bindings"] = bindings
    target = config.getoption("--qa-ac")
    if target:
        deselected = [item for item in items if item._qa_ac != target]
        items[:] = [item for item in items if item._qa_ac == target]
        config.hook.pytest_deselected(items=deselected)


def pytest_bdd_before_scenario(request):
    if hasattr(request.node, "_qa_ac"):
        request.node._qa_observation = request.getfixturevalue("observation")


def pytest_bdd_before_step_call(request, step, step_func):
    if hasattr(request.node, "_qa_ac"):
        request.node._qa_observation.step_kind = step.type
        request.node._qa_bound = step_func


def pytest_bdd_after_step(request):
    if hasattr(request.node, "_qa_ac"):
        request.node._qa_observation.step_kind = None
        request.node._qa_bound = None


def pytest_bdd_step_error(request, step, step_func, exception):
    item = request.node
    if not hasattr(item, "_qa_ac"):
        return
    result = item._qa_result
    result["step_line"] = step.line_number
    if (
        type(exception) is BehaviorMismatch
        and step.type == "then"
        and getattr(item, "_qa_bound", None) is step_func
    ):
        result.update(status="behavior_failure", reason=exception.code)
    elif isinstance(exception, (ObservationError, BrowserTimeout, AssertionError)):
        result.update(status="ambiguous", reason="Step failed without a verified behavioral mismatch.")
    elif isinstance(exception, BrowserError):
        result.update(status="invalid", reason="Playwright execution failed.")
    else:
        result.update(status="invalid", reason="Step or fixture raised an unexpected exception.")


def pytest_bdd_step_func_lookup_error(request):
    if hasattr(request.node, "_qa_result"):
        request.node._qa_result.update(status="invalid", reason="Undefined step at execution.")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not hasattr(item, "_qa_ac"):
        return
    result = item._qa_result
    if report.failed or report.skipped:
        item._qa_failed = True
        if report.when != "call" or result["status"] == "unexecuted":
            result.update(status="invalid", reason=f"Pytest {report.when} did not complete.")
    if report.when == "call":
        observation = getattr(item, "_qa_observation", None)
        result["checks"] = sorted(observation.checks if observation else ())
        if report.passed:
            if observation and observation.checks == REQUIRED_CHECKS[item._qa_ac]:
                result.update(status="passed")
            else:
                result.update(status="invalid", reason="One or more required Then checks did not run.")
                item._qa_failed = True
    item.config._qa_evidence["cases"][item._qa_ac] = result


def pytest_sessionfinish(session, exitstatus):
    destination = session.config.getoption("--qa-evidence")
    if destination:
        atomic_json(Path(destination) / "execution.json", session.config._qa_evidence)
