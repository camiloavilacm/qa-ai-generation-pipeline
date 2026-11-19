"""Shared paths, hashes and safe process/report helpers."""

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = "requirements/SEED-1.md"
CONTRACTS = ("contracts/api-expectations.json", "contracts/envelopes.json", "contracts/selectors.json")
SKILLS = (".agents/skills/generate-gherkin/SKILL.md", ".agents/skills/generate-steps/SKILL.md")
DRAFT = "drafts/SEED-1/login.feature"
FEATURE = "features/auth/login.feature"
RECEIPT = "approvals/login.feature.sha256"
AC_IDS = ("AC-1", "AC-2", "AC-3")
SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}")


class PipelineError(Exception):
    """A stage cannot continue."""


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def regular_path(root, name, *, required=True):
    path = root
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise PipelineError(f"Expected a repository-relative path: {name}")
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise PipelineError(f"Symlinks are forbidden in pipeline paths: {name}")
    if path.exists() and not path.is_file():
        raise PipelineError(f"Expected a regular file: {name}")
    if required and not path.is_file():
        raise PipelineError(f"Missing {name}")
    return path


def hashes(root, names):
    return {name: digest(regular_path(root, name).read_bytes()) for name in names}


def git(root, *args):
    result = subprocess.run(
        ["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    if result.returncode:
        # A ref or path from the environment may contain sensitive text.
        raise PipelineError(f"Git {args[0]} failed. Check the working tree and base ref.")
    return result.stdout


def atomic_json(path: Path, data: Mapping):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp = Path(handle.name)
        try:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise PipelineError(f"Missing or invalid JSON file: {path.name}") from exc


def child_env():
    # Preserve prerequisites for Python/Chromium, not user or CI credentials.
    allowlist = (
        "PATH", "HOME", "USERPROFILE", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT",
        "LANG", "LC_ALL", "XDG_CACHE_HOME", "PLAYWRIGHT_BROWSERS_PATH",
    )
    return {key: os.environ[key] for key in allowlist if key in os.environ}
