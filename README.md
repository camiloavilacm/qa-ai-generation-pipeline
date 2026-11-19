# SEED-1 · AI-assisted test generation

This repository turns one written requirement into reviewed Gherkin and
executable pytest-bdd tests. Chromium runs against a local synthetic login
app. A deterministic runner checks two isolated baselines, a separate
unauthenticated API request, and five single-fault app runs.

The trusted base contains the requirement, contracts, app, tools, CI and
two Codex skills. It is intentionally empty of generated scenarios, step
definitions, and approval receipts. The infrastructure checks run
independently of a live Codex demonstration.

## Set up and freeze the base

Use Git, Python 3.12 and a Codex CLI session for generation. These commands
assume Linux or macOS and start at the Git root.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q --tb=no tests/test_contract_and_tools.py
```

If Python 3.12 is managed by `uv`, use the following setup.

```sh
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q --tb=no tests/test_contract_and_tools.py
```

On Linux, use `python -m playwright install --with-deps chromium` if the
host lacks browser dependencies. To inspect the unmutated app manually,
run `python -m app.server --port 8000`, open
[the local login page](http://127.0.0.1:8000/login) and stop it with Ctrl+C.
Fault runs use private instrumentation and their own loopback ports.

If this is an uncommitted checkout, review and commit the trusted base
on `main` as the maintainer. Skip the initial commit for an existing clean
base. For the GitHub demonstration, the trusted base must be present on
`origin/main`. Publish it only with the owner's authorization.

```sh
git add AGENTS.md README.md .agents .github .gitignore app contracts docs \
  pyproject.toml requirements requirements-dev.txt tests tools
git commit -m "Build trusted SEED-1 pipeline"
# When authorized to publish the trusted base
git push -u origin main
```

## Generate the Gherkin

```sh
git switch -c demo/seed-1
python tools/pipeline.py begin SEED-1
codex --sandbox workspace-write --ask-for-approval on-request
```

`begin` starts the app once to check health and records the base revision,
requirement, contract and skill SHA-256 hashes in `reports/session.json`.
Start the CLI in a fresh session from this branch. Type `$` to select
`generate-gherkin` and submit this prompt with the skill mention.

> $generate-gherkin Draft SEED-1 from the frozen requirement and local contracts. Stop after validating the draft for human review.

Keep the Codex session separate from implementation and from any upstream
reference. Exit and retain the session ID and observed model in your demo
notes. If skill selection is unavailable, use the explicit prompt below.
An explicit path prompt runs the instructions but does not verify native
skill selection.

> Read .agents/skills/generate-gherkin/SKILL.md and follow it for SEED-1. Stop after validating the draft.

## Gate 1 · Human approval

Run in your own interactive terminal outside Codex. Read
`drafts/SEED-1/login.feature` and verify each item in the printed semantic
checklist. When you approve it, type `APPROVE <the printed SHA-256>` at the
prompt. This copies the reviewed bytes and writes the receipt. Commit the
two files together before starting step generation.

```sh
python tools/pipeline.py validate-draft SEED-1
cat drafts/SEED-1/login.feature
python tools/pipeline.py approve-gherkin SEED-1
git add features/auth/login.feature approvals/login.feature.sha256
git commit -m "Approve SEED-1 Gherkin"
```

The receipt binds bytes to the reviewed draft. The operator's identity is
established by the human process and repository review. A process that can
write under the same OS identity could create a matching hash and commit.

## Generate and verify the steps

```sh
python tools/pipeline.py preflight-steps SEED-1
codex --sandbox workspace-write --ask-for-approval on-request
```

Use a fresh Codex session. Select `generate-steps` using `$` and submit this
prompt. Record its session ID and model separately.

> $generate-steps Implement the approved SEED-1 scenarios with pytest-bdd and Chromium using the trusted fixtures. Run local verification and follow the repair limit.

If native skill selection is unavailable, submit this explicit prompt.

> Read .agents/skills/generate-steps/SKILL.md and follow it for SEED-1. Run preflight before editing.

If a model identifier was observed, record it using the matching stage
`gherkin` or `steps`. Replace `OBSERVED_ID` with the identifier read in the
session.

```sh
python tools/pipeline.py record-model SEED-1 --stage gherkin --model OBSERVED_ID
python tools/pipeline.py record-model SEED-1 --stage steps --model OBSERVED_ID
python tools/pipeline.py verify SEED-1
```

Preflight verifies the committed approval. Verification collects the
approved bindings, checks the complete suite against two newly seeded
app processes, and checks a bare `GET /api/user` on a third process. A failed
baseline or 401 check stops all mutant runs. Each mutant runs only its
targeted AC against a fresh app. The runner needs a trusted branch hit
and an attributable behavioral assertion failure to count a kill.

If verification fails, inspect the newest `reports/run-*/SUMMARY.md` and
`traceability.json`. Use `python tools/pipeline.py repair-start SEED-1
--reason "Describe the failed check"` **before** changing generated files.
Run `verify` again to close the attempt and record the results and diff.
Two repairs are available. A failed second repair ends the demonstration
with the recorded failure.

## Prepare the PR and complete Gate 2

Review the passing evidence, then commit the verified files and prepare
the local body.

```sh
git add tests/steps tests/pages
git commit -m "Generate executable SEED-1 tests"
python tools/pipeline.py prepare-pr SEED-1
```

After the owner authorizes publication, use an authenticated GitHub CLI
to push and open the PR. Add the GitHub Actions run link after CI executes.

```sh
git push -u origin demo/seed-1
gh pr create --base main --head demo/seed-1 \
  --title "Generate executable SEED-1 tests" --body-file reports/PR_BODY.md
gh pr checks --watch
```

A human reviewer uses the PR checklist to inspect traceability, actual
assertions, changed files and CI outcomes. Merge is optional and manual.

## Evidence, scope and troubleshooting

- `reports/run-*/` contains baseline and mutation JSON, traceability,
  redacted JUnit XML and a sanitized Playwright action timeline on failures
  where tracing starts. Raw trace ZIPs are temporary. Reports omit raw
  headers, request/response bodies, storage snapshots, credentials, and
  screenshots. Review artifacts before sharing them. The evidence filter
  is designed for trusted output fields and familiar credential formats.
- `python -m tools.validate_scope --base main` checks the committed tree.
  The complete PR can add the approved feature and receipt in one commit
  and regular Python files under `tests/steps/` and `tests/pages/`. The draft
  and local reports are ignored. The validator compares protected file
  bytes against the Git merge base.
- Workspace-write with on-request approvals supports human oversight.
  Instructions and lint checks cannot confine a process with broader OS
  access. Use the sandbox, keep the session away from the held-out feature
  and review all changes. If the agent cannot launch Chromium under the
  sandbox, run `verify` from your own terminal after inspecting the diff.
- Push CI on `main` runs infrastructure tests. PR CI runs generated
  verification with read-only token permissions and no model credentials.
  A regular `pull_request` job can execute workflow or script changes from
  a PR. Configure required checks and code-owner review in the `main`
  ruleset. CODEOWNERS uses the configured upstream owner `@camiloavilacm`.
  Those repository settings are applied by the owner on GitHub.
- Project skill discovery and explicit skill loading were checked with
  Codex CLI 0.170.0. On Apple Silicon, use a native terminal if an x86
  Node shell reports a missing Codex optional dependency. Verify with
  `arch -arm64 /bin/zsh -lc 'codex --version'`.
- For missing or ambiguous bindings, read the initial collection diagnostic
  in `verification.json` and check that all approved steps bind exactly
  once. For browser startup failures check the Chromium installation and
  confirm your shell points at `.venv/bin/python`.

The contract fixtures reproduce the approved upstream API and selector
files at the pinned revision. The upstream API file is JSON-formatted
despite its extension. `contracts/envelopes.json` supplies the local
request/response schema for the synthetic app. [API expectations](https://github.com/camiloavilacm/qa-features/blob/e7c566ff831139889195643a1b906b7edab76f48/api-expectations.yaml) · [Selectors](https://github.com/camiloavilacm/qa-features/blob/e7c566ff831139889195643a1b906b7edab76f48/selectors.json)

Codex CLI paths and flags follow the official documentation. [Project skills](https://learn.chatgpt.com/docs/build-skills) · [CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) · [GitHub code-owner rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
