"""Human-gated SEED-1 generation, verification and PR preparation."""

import argparse
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_NB, flock
from difflib import unified_diff
from pathlib import Path
import re
import shutil
import sys
from tempfile import mkdtemp

# Support both python tools/pipeline.py and python -m tools.pipeline.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common import (
    AC_IDS, CONTRACTS, DRAFT, FEATURE, RECEIPT, REQUIREMENT, ROOT, SAFE_MODEL, SKILLS,
    PipelineError, atomic_json, digest, git, hashes, load_json, regular_path,
)
from tools.run_mutants import execute_verification, start_app
from tools.validate_scope import check_approval_commit, check_scope, generated_hashes, merge_base, resolve_commit
from tools.validate_traceability import SENSITIVE_TEXT, approved_feature, feature_structure, lint_generated

REPORTS = "reports"
SESSION = f"{REPORTS}/session.json"
LATEST = f"{REPORTS}/validation.json"
CHECKLIST = (
    "Background verifies the immutable baseline and starts with fresh cookies and both storage areas.",
    "AC-1 registers a unique identity and verifies the API identity/token, browser session, and settings email.",
    "AC-2 signs in with the seeded credentials and verifies the API identity/token, browser session, and settings email.",
    "AC-3 verifies the exact API and UI errors, no authentication, direct settings denial, login heading, and absent identity.",
)


def branch(root):
    return git(root, "symbolic-ref", "--short", "HEAD").decode().strip()


def head(root):
    return git(root, "rev-parse", "HEAD").decode().strip()


def input_hashes(root):
    return hashes(root, (REQUIREMENT, *CONTRACTS, *SKILLS))


def begin(root, base):
    name = branch(root)
    rev = resolve_commit(root, base)
    if name in ("main", base) or head(root) != rev:
        raise PipelineError("Create a new demo branch directly from the frozen trusted base.")
    check_scope(root, rev, stage="draft")
    if regular_path(root, DRAFT, required=False).exists():
        raise PipelineError("Begin on a clean branch with no existing draft.")
    if any((root / path).exists() for path in (FEATURE, RECEIPT)):
        raise PipelineError("The generation base must have an empty approval stage.")
    session = {
        "branch": name, "base": rev, "inputs": input_hashes(root),
        "models": {}, "repairs": [], "pending": None, "last": None,
    }
    saved = regular_path(root, SESSION, required=False)
    if saved.exists() and load_json(saved)["branch"] == name:
        raise PipelineError("This branch already has a session. Preserve its recorded history.")
    with start_app(root):
        pass
    atomic_json(saved, session)
    print(f"Prepare complete on {name}. Input hashes are in {SESSION}. App health passed.")
    print(f"Run generate-gherkin to create {DRAFT}.")


def get_session(root):
    session = load_json(regular_path(root, SESSION))
    if session["branch"] != branch(root) or merge_base(root, session["base"]) != session["base"]:
        raise PipelineError("The current branch and frozen base must match the session.")
    if session["inputs"] != input_hashes(root):
        raise PipelineError("Requirement, contract or skill hashes changed since begin.")
    return session


def draft_review(root):
    session = get_session(root)
    check_scope(root, session["base"], stage="draft")
    data = regular_path(root, DRAFT).read_bytes()
    structure = feature_structure(data)
    print(f"Gherkin structure valid. Draft SHA-256 {digest(data)}")
    for ac in AC_IDS:
        print(f"  {ac}  {structure[ac]['title']}")
    print("Gate 1 semantic checklist for the human reviewer")
    for item in CHECKLIST:
        print(f"  [ ] {item}")
    return data


def approve_gherkin(root):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise PipelineError("Gate 1 requires a human at an interactive terminal.")
    data = draft_review(root)
    sha = digest(data)
    paths = [regular_path(root, name, required=False) for name in (FEATURE, RECEIPT)]
    if any(path.exists() for path in paths):
        raise PipelineError("Approval already exists. The Gate 1 artifacts may only be introduced once.")
    answer = input(f"After checking the draft yourself, type APPROVE {sha}\n> ")
    if answer != f"APPROVE {sha}":
        raise PipelineError("Human approval was not confirmed.")
    if regular_path(root, DRAFT).read_bytes() != data:
        raise PipelineError("The draft changed during review. Review the new bytes.")
    created = []
    try:
        for path, content in zip(paths, (data, (sha + "\n").encode()), strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                created.append(path)
                handle.write(content)
    except OSError as exc:
        for path in created:
            path.unlink()
        raise PipelineError("Could not write the two new Gate 1 files.") from exc
    print(f"Gate 1 recorded {sha}. Commit {FEATURE} and {RECEIPT} together before generating steps.")


def check_steps(root, base, *, committed=False):
    check_scope(root, base, committed=committed)
    sha, structure = approved_feature(root)
    return sha, structure


def print_results(result):
    print(f"Verification {'passed' if result['passed'] else 'blocked'}")
    for baseline in result["baselines"]:
        print(f"  {baseline['name']:<13} {'passed' if baseline['passed'] else 'failed'}")
    print(f"  API 401       {result['api']['status']}")
    if result["mutants"]:
        print(f"  {'Fault':<34} {'AC':<5} {'Hits':>4}  Outcome")
        for row in result["mutants"]:
            print(f"  {row['fault']:<34} {row['ac']:<5} {row['fault_hits']:>4}  {row['outcome']}")
    print(f"Evidence {REPORTS}/{result['report_dir']}/")
    if result["failure"]:
        print(result["failure"])


def verification(root, base, *, session=None, committed=False):
    sha, structure = check_steps(root, base, committed=committed)
    files = generated_hashes(root)
    if session and session["last"] and files != session["last"]["files"] and not session["pending"]:
        raise PipelineError("Record a repair reason before changing a failed generated implementation.")
    if session and session["pending"] and files == session["last"]["files"]:
        raise PipelineError("The open repair has no generated code changes.")
    if session and session["last"] and sha != session["last"]["feature_sha256"]:
        raise PipelineError("The approved feature changed after verification.")

    report_root = root / REPORTS
    report_root.mkdir(exist_ok=True)
    folder = Path(mkdtemp(prefix="run-", dir=report_root))
    trusted_inputs = input_hashes(root)
    try:
        lint_generated(root, files)
    except PipelineError as exc:
        result = {"baselines": [], "mutants": [], "api": {"status": "not_run"}, "failure": str(exc)}
    else:
        result = execute_verification(root, folder)

    # Check the approved bytes, protected Git scope and every generated file
    # again after running untrusted test modules.
    checked_sha, _ = check_steps(root, base, committed=committed)
    if checked_sha != sha or generated_hashes(root) != files or input_hashes(root) != trusted_inputs:
        raise PipelineError("Verification inputs changed during execution.")

    result.update(
        schema_version=1, requirement="SEED-1", git_sha=head(root), git_base=base,
        feature_sha256=sha, gate1_commit=check_approval_commit(root, base),
        files=files, input_sha256=trusted_inputs,
        models=session["models"] if session else {}, passed=result["failure"] is None,
        report_dir=folder.name,
    )
    saved_snapshot = None
    if session:
        if session["pending"]:
            saved_snapshot = root / REPORTS / session["pending"]["snapshot"]
            finish_repair(root, session, result)
        session["last"] = {
            "passed": result["passed"], "report_dir": folder.name, "files": files, "feature_sha256": sha,
        }
    result["repairs"] = session["repairs"] if session else []
    atomic_json(folder / "verification.json", result)
    atomic_json(folder / "mutations.json", {"mutants": result["mutants"]})
    atomic_json(folder / "baselines.json", {"baselines": result["baselines"], "independent_api": result["api"]})
    atomic_json(folder / "traceability.json", traceability(structure, result))
    (folder / "SUMMARY.md").write_text(evidence_summary(result), encoding="utf-8")
    atomic_json(root / LATEST, result)
    if session:
        atomic_json(root / SESSION, session)
    if saved_snapshot:
        shutil.rmtree(saved_snapshot, ignore_errors=True)
    print_results(result)
    return result


def traceability(structure, result):
    bound = {
        row["ac"]: {step["line"]: step["function"] for step in row["steps"]}
        for row in result.get("collection", {}).get("bindings", [])
    }
    criteria = {}
    for ac, scenario in structure.items():
        bindings = bound.get(ac, {})
        criteria[ac] = {
            "scenario": scenario["title"],
            "bound_steps": [
                {"kind": step["kind"], "line": step["line"], "function": bindings.get(step["line"])}
                for step in scenario["steps"]
            ],
            "baselines": {
                row["name"]: row["cases"].get(ac, {"status": "not_run"})
                for row in result["baselines"]
            },
            "mutants": [row for row in result["mutants"] if row["ac"] == ac],
        }
    return {
        "schema_version": 1,
        "feature_sha256": result["feature_sha256"],
        "acceptance_criteria": criteria,
    }


def start_repair(root, session, reason):
    sha, _ = check_steps(root, session["base"])
    last = session["last"]
    if session["pending"] or not last or last["passed"]:
        raise PipelineError("Start a repair only after a failed verification with no open repair.")
    if len(session["repairs"]) >= 2:
        raise PipelineError("Both allowed repair attempts are exhausted.")
    if sha != last["feature_sha256"] or generated_hashes(root) != last["files"]:
        raise PipelineError("Repair must start from the exact verified feature and generated files.")
    reason = " ".join(reason.split())
    if not reason or len(reason) > 300 or SENSITIVE_TEXT.search(reason):
        raise PipelineError("Use a short, credential-free repair reason.")
    number = len(session["repairs"]) + 1
    snapshot = Path(mkdtemp(prefix=f"repair-{number}-", dir=root / REPORTS))
    for name in last["files"]:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(regular_path(root, name), path)
    session["pending"] = {"attempt": number, "reason": reason, "before": last["report_dir"], "snapshot": snapshot.name}
    atomic_json(root / SESSION, session)
    print(f"Repair {number} opened. Edit only generated code, then run verify.")


def finish_repair(root, session, result):
    pending = session["pending"]
    snapshot = root / REPORTS / pending["snapshot"]
    old, new = session["last"]["files"], result["files"]
    changed = [name for name in sorted(old.keys() | new.keys()) if old.get(name) != new.get(name)]
    patch = []
    for name in changed:
        before = (snapshot / name).read_text(errors="replace") if name in old else ""
        after = regular_path(root, name).read_text(errors="replace") if name in new else ""
        patch.extend(unified_diff(before.splitlines(True), after.splitlines(True), f"a/{name}", f"b/{name}"))
    destination = root / REPORTS / result["report_dir"] / f"repair-{pending['attempt']}.diff"
    # A failed lint may contain sensitive text. Drop any matching line in full.
    safe_patch = "".join(
        "[credential-like diff line removed]\n" if SENSITIVE_TEXT.search(line) else line for line in patch
    )
    destination.write_text(safe_patch, encoding="utf-8")
    entry = {key: pending[key] for key in ("attempt", "reason", "before")}
    entry.update(
        before_passed=session["last"]["passed"], after=result["report_dir"],
        passed=result["passed"], changed_files=changed, diff=destination.name,
    )
    session["repairs"].append(entry)
    session["pending"] = None


def evidence_summary(result):
    rows = [
        "# SEED-1 verification", "", f"Result **{'passed' if result['passed'] else 'failed'}**", "",
        f"- Git SHA {result['git_sha']}", f"- Approved feature SHA-256 {result['feature_sha256']}",
        f"- Independent API 401 {result['api']['status']}", "",
        "## Baselines", "",
        *(f"- {row['name']} {'passed' if row['passed'] else 'failed'}" for row in result["baselines"]),
        "", "## Mutants", "", "| Fault | AC | Hits | Outcome | Reason |",
        "| --- | --- | ---: | --- | --- |",
        *(f"| {row['fault']} | {row['ac']} | {row['fault_hits']} | {row['outcome']} | {row['reason']} |"
          for row in result["mutants"]),
    ]
    if result["failure"]:
        rows.extend(["", result["failure"]])
    return "\n".join(rows) + "\n"


def prepare_pr(root, session):
    sha, _ = check_steps(root, session["base"], committed=True)
    if session["pending"] or not session["last"] or not session["last"]["passed"]:
        raise PipelineError("Complete successful verification before preparing the PR.")
    folder = root / REPORTS / session["last"]["report_dir"]
    result = load_json(folder / "verification.json")
    if sha != result["feature_sha256"] or generated_hashes(root) != result["files"] or not result["passed"]:
        raise PipelineError("The committed approval and generated code must match passing evidence.")
    mapping = load_json(folder / "traceability.json")["acceptance_criteria"]
    rows = [
        "# SEED-1 · Generated login checks", "",
        f"- Requirement SHA-256 {result['input_sha256'][REQUIREMENT]}",
        f"- Approved feature SHA-256 {sha}", f"- Gate 1 commit {result['gate1_commit']}",
        f"- Commit to review {head(root)}",
        f"- Commit used for local verification {result['git_sha']}", "",
        "## Generation provenance", "",
        *(f"- {stage} model {session['models'].get(stage, 'unrecorded')}" for stage in ("gherkin", "steps")),
        *(f"- {skill} SHA-256 {result['input_sha256'][skill]}" for skill in SKILLS), "",
        *(f"- {name} SHA-256 {result['input_sha256'][name]}" for name in CONTRACTS),
        f"- Independent bare current-user request {result['api']['status']}", "",
        "## Traceability", "",
        *(f"- {ac} · {clean_title(row['scenario'])} · {len(row['bound_steps'])} bound steps"
          for ac, row in mapping.items()), "",
        "## Baselines" + evidence_summary(result).split("## Baselines", 1)[1],
        "## Repairs", "",
        *(f"- Attempt {entry['attempt']} · {entry['reason']} · "
          f"{'passed' if entry['passed'] else 'failed'} · {', '.join(entry['changed_files'])} · "
          f"local diff {entry['after']}/{entry['diff']}"
          for entry in result["repairs"]),
        *(["No repairs recorded."] if not result["repairs"] else []), "",
        "## Changed files", "",
        *(f"- {name}" for name in (FEATURE, RECEIPT, *sorted(result["files"]))), "",
        "## GitHub review", "",
        "CI run link pending GitHub Actions execution.", "",
        "- [ ] Review the approved feature and committed SHA-256 receipt.",
        "- [ ] Inspect AC mapping, actual step assertions and protected-file scope.",
        "- [ ] Confirm two isolated baseline passes and five valid targeted mutant kills in CI.",
        "- [ ] Check downloadable reports for unexpected data before sharing.",
    ]
    destination = regular_path(root, f"{REPORTS}/PR_BODY.md", required=False)
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"PR body ready at {REPORTS}/PR_BODY.md for committed branch {session['branch']}.")


def clean_title(text):
    return re.sub(r"[^ A-Za-z0-9.,()/_-]", "", text)[:120]


@contextmanager
def stage_lock(root):
    lock = regular_path(root, f"{REPORTS}/.pipeline.lock", required=False)
    lock.parent.mkdir(exist_ok=True)
    with lock.open("a") as handle:
        try:
            flock(handle, LOCK_EX | LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError("Another pipeline command is running in this workspace.") from exc
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "begin", "validate-draft", "approve-gherkin", "preflight-steps", "record-model",
        "verify", "repair-start", "prepare-pr", "ci",
    ):
        command = commands.add_parser(name)
        command.add_argument("requirement", choices=["SEED-1"])
        if name in ("begin", "ci"):
            command.add_argument("--base", default="main")
        if name == "repair-start":
            command.add_argument("--reason", required=True)
        if name == "record-model":
            command.add_argument("--stage", choices=("gherkin", "steps"), required=True)
            command.add_argument("--model", required=True)
    args = parser.parse_args()
    try:
        with stage_lock(ROOT):
            if args.command == "begin":
                begin(ROOT, args.base)
            elif args.command == "validate-draft":
                draft_review(ROOT)
            elif args.command == "approve-gherkin":
                approve_gherkin(ROOT)
            elif args.command == "ci":
                result = verification(ROOT, merge_base(ROOT, args.base), committed=True)
                return 0 if result["passed"] else 1
            else:
                session = get_session(ROOT)
                if args.command == "preflight-steps":
                    sha, _ = check_steps(ROOT, session["base"])
                    print(f"Gate 1 is committed and the exact SHA-256 {sha} matches. Step generation may start.")
                elif args.command == "record-model":
                    if not SAFE_MODEL.fullmatch(args.model) or SENSITIVE_TEXT.search(args.model):
                        raise PipelineError("Record the observed model identifier only.")
                    session["models"][args.stage] = args.model
                    atomic_json(ROOT / SESSION, session)
                    print("Recorded the operator-supplied model identifier.")
                elif args.command == "verify":
                    result = verification(ROOT, session["base"], session=session)
                    return 0 if result["passed"] else 1
                elif args.command == "repair-start":
                    start_repair(ROOT, session, args.reason)
                elif args.command == "prepare-pr":
                    prepare_pr(ROOT, session)
    except (PipelineError, OSError, EOFError) as exc:
        # PipelineError messages use redacted diagnostics. Avoid OS exceptions
        # carrying arbitrary filenames outside the known repository paths.
        message = str(exc) if isinstance(exc, PipelineError) else "A required local file or terminal was unavailable."
        print(f"{args.command} blocked. {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
