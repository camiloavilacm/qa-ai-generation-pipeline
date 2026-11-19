---
name: generate-steps
description: Bind the human-approved SEED-1 feature to pytest-bdd and implement the Playwright interactions and checks.
---

Run `python tools/pipeline.py preflight-steps SEED-1` before editing. Stop if
the committed Gate 1 receipt or exact feature hash fails verification. Read
the approved feature, local contracts and `docs/fixtures.md`.

Write only `tests/steps/**` and `tests/pages/**`. Bind each approved scenario
once using pytest-bdd. Use page objects and approved semantic locators for
real Chromium interactions. Call the trusted `check` fixture from the
appropriate Then steps to assert observations against the contract. Keep
actions outcome-neutral so a rejected action can reach its behavioral
assertion. Use the supplied identities and fresh page. Do not stub or alter
auth state or read mutation flags and counters.

Run `python tools/pipeline.py verify SEED-1`. If it fails, read its redacted
evidence. Run `python tools/pipeline.py repair-start SEED-1 --reason "..."`
before editing. Change only generated code and rerun `verify` after each
repair. Stop after two attempts or a passing verification. Return the
evidence path and any unresolved failure. Leave approval, committing,
pushing, PR creation and final review to the human operator.
