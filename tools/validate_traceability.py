"""Parse the restricted demo Gherkin and lint generated Python before execution."""

import ast
from collections import Counter
from pathlib import Path
import re

from gherkin.parser import Parser
from gherkin.errors import CompositeParserException

from tools.common import AC_IDS, FEATURE, RECEIPT, PipelineError, digest, regular_path

# Evidence only displays explicitly permitted text. Do not include parser exceptions
# that may echo arbitrary Gherkin source, secrets or generated code.
SENSITIVE_TEXT = re.compile(
    r"qa\.jwt\.|qa-fixture-|baseline-fixture-password|invalid-fixture-password"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|authorization\s*[=:]\s*(?:bearer|token)\s+\S+",
    re.IGNORECASE,
)


def feature_structure(source):
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PipelineError("The Gherkin must be UTF-8.") from exc
    if SENSITIVE_TEXT.search(text) or re.search(r"\bmatrix slot\b", text, re.IGNORECASE):
        raise PipelineError("The Gherkin contains restricted content.")
    try:
        feature = Parser().parse(text).get("feature")
    except CompositeParserException as exc:
        raise PipelineError("Malformed Gherkin. Check keywords, tags and step syntax.") from exc
    if not feature or feature["language"] != "en" or feature["keyword"] != "Feature":
        raise PipelineError("Expected one English-language Feature.")
    if [tag["name"] for tag in feature["tags"]] != ["@SEED-1"]:
        raise PipelineError("Tag the feature exactly @SEED-1.")

    children = feature["children"]
    if len(children) != 4 or "background" not in children[0]:
        raise PipelineError("Expected one leading Background and exactly three scenarios.")
    background = steps_for(children[0]["background"], "background")
    if any(step["kind"] != "given" for step in background):
        raise PipelineError("The Background may contain only setup steps (Given/And).")
    scenarios = {}
    titles = set()
    for child in children[1:]:
        scenario = child.get("scenario")
        if not scenario or scenario["keyword"] != "Scenario" or scenario["examples"]:
            raise PipelineError("Use plain Scenario blocks for AC-1 through AC-3.")
        tags = [tag["name"] for tag in scenario["tags"]]
        if len(tags) != 1 or tags[0][1:] not in AC_IDS:
            raise PipelineError("Each scenario must have exactly one known AC tag.")
        ac = tags[0][1:]
        title = scenario["name"].strip()
        if ac in scenarios or not title or title in titles:
            raise PipelineError("Scenario titles and AC tags must be present and unique.")
        steps = steps_for(scenario, "scenario")
        kinds = [step["kind"] for step in steps]
        if "when" not in kinds or "then" not in kinds or kinds[-1] != "then":
            raise PipelineError(f"{ac} needs executable When and Then steps.")
        scenarios[ac] = {"title": title, "steps": background + steps}
        titles.add(title)
    if set(scenarios) != set(AC_IDS):
        raise PipelineError("The feature must cover exactly AC-1, AC-2 and AC-3.")
    return scenarios


def steps_for(block, source):
    steps = []
    kind = None
    for step in block["steps"]:
        keyword = step["keyword"].strip()
        if keyword in ("Given", "When", "Then"):
            kind = keyword.lower()
        elif keyword not in ("And", "But") or kind is None:
            raise PipelineError(f"Use Given, When, Then, And or But in the {source}.")
        if not step["text"].strip() or "dataTable" in step or "docString" in step:
            raise PipelineError(f"Use nonempty single-line steps in the {source}.")
        steps.append({"kind": kind, "text": step["text"], "line": step["location"]["line"]})
    if not steps:
        raise PipelineError(f"Missing executable steps in the {source}.")
    return steps


def approved_feature(root):
    path = regular_path(root, FEATURE)
    data = path.read_bytes()
    receipt = regular_path(root, RECEIPT).read_bytes()
    sha = digest(data)
    if receipt != (sha + "\n").encode():
        raise PipelineError("Approval SHA-256 does not match the exact feature bytes.")
    return sha, feature_structure(data)


SAFE_MODULES = {
    "__future__", "collections", "dataclasses", "functools", "json", "re",
    "typing", "urllib.parse", "uuid", "pytest_bdd", "pytest", "playwright.sync_api",
}
FORBIDDEN_NAMES = {
    "breakpoint", "compile", "eval", "exec", "getattr", "setattr", "delattr", "globals",
    "locals", "open", "vars", "__import__", "sleep", "wait_for_timeout", "skip", "skipif",
    "xfail", "importorskip", "fail", "route", "route_from_har", "unroute", "fulfill",
    "add_init_script", "add_cookies", "clear_cookies", "storage_state", "dispatch_event",
    "request", "new_context", "new_page", "set_content", "pytest_plugins", "monkeypatch",
    "getfixturevalue", "tracing", "fixture", "parametrize",
}
STORAGE_WRITE = re.compile(r"\b(?:setItem|removeItem|clear)\s*\(|document\.cookie\s*=", re.IGNORECASE)


def lint_generated(root, files):
    if not any(name.startswith("tests/steps/test_") for name in files):
        raise PipelineError("Add a pytest-bdd module under tests/steps/test_*.py.")
    if not any(name.startswith("tests/pages/") and Path(name).name != "__init__.py" for name in files):
        raise PipelineError("Add a Playwright page object under tests/pages/.")
    for name in files:
        text = regular_path(root, name).read_text(encoding="utf-8")
        if SENSITIVE_TEXT.search(text) or "BUG_" in text or "X-QA-Session" in text or STORAGE_WRITE.search(text):
            raise PipelineError(f"Restricted test content in {name}.")
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError as exc:
            raise PipelineError(f"Invalid Python syntax in {name} at line {exc.lineno}.") from exc
        for node in ast.walk(tree):
            if violates_policy(node):
                raise PipelineError(f"Forbidden generated construct in {name} at line {node.lineno}.")


def violates_policy(node):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.ImportFrom):
            return node.level != 0 or not safe_module(node.module) or any(
                alias.name == "*" or alias.name in FORBIDDEN_NAMES for alias in node.names
            )
        return any(not safe_module(alias.name) for alias in node.names)
    if isinstance(node, ast.Name):
        return node.id in FORBIDDEN_NAMES or node.id.startswith("pytest_")
    if isinstance(node, ast.Attribute):
        return node.attr in FORBIDDEN_NAMES or node.attr.startswith("_")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name.startswith("pytest_")
    if isinstance(node, ast.keyword) and node.arg == "target_fixture":
        value = node.value.value if isinstance(node.value, ast.Constant) else None
        return not isinstance(value, str) or not value.startswith("generated_")
    if isinstance(node, ast.Assert):
        return isinstance(node.test, (ast.Constant, ast.Tuple, ast.List, ast.Dict, ast.Set))
    # No swallowing assertion errors (including via try/finally with return),
    # conditional test suppression, or synthetic behavioral exception.
    return isinstance(node, (ast.Try, ast.TryStar, ast.Raise, ast.Global, ast.Nonlocal))


def safe_module(name):
    return name in SAFE_MODULES or bool(name and (name == "tests.pages" or name.startswith("tests.pages.")))


def check_bindings(structure, collection):
    expected = Counter(AC_IDS)
    observed = Counter(row["ac"] for row in collection)
    if observed != expected:
        raise PipelineError("Collect exactly one pytest-bdd test for each approved AC.")
    for row in collection:
        scenario = structure[row["ac"]]
        if row["title"] != scenario["title"] or [step["line"] for step in row["steps"]] != [
            step["line"] for step in scenario["steps"]
        ]:
            raise PipelineError("Collected step binding does not match the approved feature.")
