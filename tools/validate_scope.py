"""Validate generation changes against the Git merge base and approval commit."""

import argparse
from pathlib import Path
import re

from tools.common import DRAFT, FEATURE, RECEIPT, ROOT, PipelineError, git, hashes, regular_path

GENERATED = re.compile(r"tests/(?:steps|pages)/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py")
APPROVAL_PATHS = (FEATURE, RECEIPT)


def is_generated(path):
    return bool(GENERATED.fullmatch(path)) and Path(path).name != "conftest.py"


def resolve_commit(root, ref):
    return git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()


def merge_base(root, base):
    return git(root, "merge-base", resolve_commit(root, base), "HEAD").decode().strip()


def raw_diff(root, *revs):
    fields = git(root, "diff", "--raw", "--no-renames", "-z", *revs, "--").split(b"\0")
    for metadata, path in zip(fields[:-1:2], fields[1::2], strict=True):
        old_mode, new_mode, _, _, status = metadata[1:].decode().split()
        yield old_mode, new_mode, status, path.decode("utf-8", errors="surrogateescape")


def check_scope(root, base, *, stage="steps", committed=False):
    base = merge_base(root, base)
    if stage == "draft":
        if git(root, "rev-parse", "HEAD").decode().strip() != base:
            raise PipelineError("Draft generation requires HEAD at the frozen base commit.")
    verify_base_files(root, base)
    allowed = is_generated if stage == "steps" else lambda path: False

    # Check both committed and staged changes even if the working copy masks an edit.
    for diff in ((base, "HEAD"), ("--cached", base), (base,)):
        for old_mode, new_mode, status, path in raw_diff(root, *diff):
            if path not in APPROVAL_PATHS or stage != "steps":
                if not allowed(path):
                    raise PipelineError(f"Disallowed change: {path!r}")
            if old_mode != "000000" or new_mode != "100644" or status != "A":
                # Git reports new worktree files as 000000 object IDs, but their mode
                # still describes the filesystem entry.
                raise PipelineError(f"Expected a new regular nonexecutable file: {path!r}")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")[:-1]
    for raw in untracked:
        path = raw.decode("utf-8", errors="surrogateescape")
        if not allowed(path):
            raise PipelineError(f"Disallowed untracked file: {path!r}")
        if regular_path(root, path).stat().st_mode & 0o111:
            raise PipelineError(f"Generated Python files must be nonexecutable: {path!r}")

    if committed and git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PipelineError("Commit the verified generated files on a clean branch first.")
    if stage == "steps":
        check_approval_commit(root, base)
    return base


def verify_base_files(root, base):
    # Compare actual bytes to Git blobs, including any paths that Git flags
    # assume-unchanged or skip-worktree might otherwise hide from the diff.
    entries = git(root, "ls-tree", "-rz", base).split(b"\0")[:-1]
    for entry in entries:
        metadata, filename = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        name = filename.decode("utf-8", errors="surrogateescape")
        if name in (*APPROVAL_PATHS, DRAFT) or name.startswith(("reference/", "tests/steps/", "tests/pages/")):
            raise PipelineError(f"Generation base contains a held-out or generated path: {name!r}")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise PipelineError(f"Unexpected trusted base file type: {name!r}")
        path = regular_path(root, name, required=False)
        if not path.exists() or path.read_bytes() != git(root, "cat-file", "blob", object_id):
            raise PipelineError(f"Disallowed change to a frozen file: {name!r}")


def check_approval_commit(root, base):
    for path in APPROVAL_PATHS:
        if regular_path(root, path).read_bytes() != git(root, "show", f"HEAD:{path}"):
            raise PipelineError(f"Approval must be committed and byte-identical: {path}")
    history = git(root, "log", "--full-history", "--format=%H", f"{base}..HEAD", "--", *APPROVAL_PATHS)
    commits = history.decode().splitlines()
    if len(commits) != 1:
        raise PipelineError("The approved feature and receipt must enter in one commit and stay unchanged.")
    entries = list(raw_diff(root, base, commits[0]))
    paths = sorted(path for old, new, status, path in entries
                   if (old, new, status) == ("000000", "100644", "A"))
    if paths != sorted(APPROVAL_PATHS) or len(entries) != len(APPROVAL_PATHS):
        raise PipelineError("The Gate 1 commit must contain exactly the approved feature and receipt.")
    return commits[0]


def generated_hashes(root):
    names = []
    for name in ("tests/steps", "tests/pages"):
        directory = root / name
        if directory.is_symlink():
            raise PipelineError(f"Symlinked generated directory: {name}")
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise PipelineError(f"Symlink in generated tree: {path.relative_to(root)}")
            if path.is_file() and "__pycache__" not in path.parts:
                name = path.relative_to(root).as_posix()
                if not is_generated(name):
                    raise PipelineError(f"Disallowed generated file: {name!r}")
                names.append(name)
    return hashes(root, sorted(names))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="main")
    args = parser.parse_args()
    try:
        base = check_scope(ROOT, args.base, committed=True)
    except PipelineError as exc:
        parser.exit(1, f"Scope blocked: {exc}\n")
    print(f"Scope OK against {base}")


if __name__ == "__main__":
    main()
