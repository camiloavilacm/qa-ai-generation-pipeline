"""Trusted SEED-1 browser fixture interface for generated tests."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import sync_playwright

from app.server import BASELINE, INVALID_PASSWORD, Identity
from tools.behavior import CONTRACT, Observation, storage_presence
from tools.playwright_trace import export_failure_trace


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def base_url(pytestconfig):
    return pytestconfig.getoption("--qa-base-url")


@pytest.fixture
def baseline_user():
    return BASELINE


@pytest.fixture
def invalid_password():
    return INVALID_PASSWORD


@pytest.fixture
def registration_user():
    suffix = uuid4().hex
    return Identity(f"qa-{suffix}", f"qa-{suffix}@example.test", f"qa-fixture-{uuid4().hex}")


@pytest.fixture
def api_contract():
    return CONTRACT


@pytest.fixture
def page(browser, base_url, request):
    context = browser.new_context(base_url=base_url)
    context.set_default_timeout(3000)
    context.set_default_navigation_timeout(5000)
    trace_dir = request.config.getoption("--qa-evidence")
    if trace_dir:
        context.tracing.start(screenshots=False, snapshots=False, sources=False)
    try:
        page = context.new_page()
        health = page.request.get("/health")
        if health.status != 200 or health.json() != {"ready": True}:
            pytest.fail("Baseline seeding health check failed.", pytrace=False)
        page.goto(CONTRACT["ui"]["login_route"])
        if context.cookies() or any(storage_presence(page).values()):
            pytest.fail("A browser context started with authentication state.", pytrace=False)
        yield page
    finally:
        try:
            if trace_dir and getattr(request.node, "_qa_failed", False):
                export_failure_trace(context, Path(trace_dir) / f"{request.node._qa_ac}-playwright-trace.json")
            elif trace_dir:
                context.tracing.stop()
        finally:
            context.close()


@pytest.fixture
def observation(page, base_url, request, baseline_user, registration_user, invalid_password):
    ac = request.node._qa_ac
    identity = {
        "AC-1": registration_user,
        "AC-2": baseline_user,
        "AC-3": replace(baseline_user, password=invalid_password),
    }[ac]
    return Observation(page, base_url, ac, identity)


@pytest.fixture
def check(observation):
    return observation.call
