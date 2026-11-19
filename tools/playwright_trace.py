"""Persist an allowlisted Playwright action timeline on failure."""

import json
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile

from tools.common import atomic_json

ACTION_ID = re.compile(r"(?:call|api|expect)@[0-9]+")
SAFE_APIS = {
    "page.goto", "page.waitForURL", "page.evaluate", "page.expectResponse", "page.waitForEvent",
    "locator.fill", "locator.click", "locator.waitFor", "locator.innerText", "locator.isVisible",
    "locator.count", "apiRequestContext.get", "browserContext.cookies",
}


def trace_events(path):
    events = []
    with ZipFile(path) as archive:
        for member in archive.namelist():
            if not member.endswith(".trace"):
                continue
            with archive.open(member) as lines:
                for line in lines:
                    value = json.loads(line)
                    phase, identifier = value.get("type"), value.get("callId")
                    if phase not in ("before", "after") or not isinstance(identifier, str):
                        continue
                    if not ACTION_ID.fullmatch(identifier):
                        continue
                    row = {"phase": phase, "id": identifier}
                    api = value.get("apiName")
                    if api in SAFE_APIS:
                        row["api"] = api
                    timestamp = value.get("startTime" if phase == "before" else "endTime")
                    if type(timestamp) in (float, int):
                        row["monotonic_ms"] = timestamp
                    if phase == "after":
                        row["failed"] = bool(value.get("error"))
                    events.append(row)
    return events


def export_failure_trace(context, destination):
    # Trace archives can include form inputs and headers even with snapshots off.
    # Keep the raw archive in a private temporary directory and publish only a
    # field allowlist. Raw network entries, call parameters and errors stay out.
    with tempfile.TemporaryDirectory(prefix="qa-private-playwright-") as temporary:
        archive = Path(temporary) / "trace.zip"
        try:
            context.tracing.stop(path=str(archive))
            data = {"status": "recorded", "actions": trace_events(archive)}
        except Exception:
            data = {"status": "unavailable", "actions": []}
        atomic_json(destination, data)
