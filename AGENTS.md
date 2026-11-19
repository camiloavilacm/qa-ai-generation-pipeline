Codex implementation brief — AI-assisted test generation pipeline
Project: qa-ai-generation-pipeline
Status of this document: implementation specification (not a claim that the demo has run)
Prepared: 2026-11-18
Primary requirement: AI-assisted test generation pipeline: requirement → Gherkin → step definitions → human review → pull request, built with Codex project instructions and reusable skills.
0. Instructions to Codex
You are the implementation engineer. Implement the project described in this file, not just another proposal. Make sensible, minimal technical choices, write the code, tests, skills, validation tools and documentation, and run all checks that are possible in the available environment. Do not claim a completed live Codex generation run, authenticated human approval, GitHub CI execution, or an opened PR unless those actions actually occurred. If those services are unavailable, deliver a working local implementation plus precise instructions for completing the live demonstration.

Important existing workspace: a starter qa-ai-generation-pipeline/ directory may already exist. Inspect it first and refactor it rather than indiscriminately replacing it. It currently may contain a prewritten features/auth/login.feature, prewritten tests/steps/test_login.py, reference/login.feature, four legacy skills, a simple HTTP app, tools/pipeline.py, and a basic CI workflow. These are starter artifacts, not proof of AI generation. In particular, a golden feature inside reference/ and existing final test steps violate the intended held-out generation exercise. Preserve useful implementation work, but correct the design. If starting in an empty repository, create the same end state from scratch.

At completion, report: (1) files added/changed, (2) commands actually executed and their results, (3) what is genuinely working, (4) what is NOT RUN, and (5) exact human-operated commands needed to run the Codex → approval → PR demonstration. Do not auto-approve, push, open, or merge a PR without explicit authorization from the human owner.
1. Goal, question and strict scope
The project must answer:
Can Codex generate executable tests from a written requirement, and can we independently show that those tests cover the intended behavior, detect deliberate faults, survive human review, and produce a reviewable GitHub PR?

Build a single standalone repository containing:
- A human-authored SEED-1 login requirement and technical contracts.
- A small synthetic login application with intentionally switchable bugs.
- Two actual Codex skills: generate-gherkin and generate-steps.
- One Python test runner: pytest-bdd + Playwright Chromium.
- Deterministic validation, a human Gherkin approval checkpoint, two baseline runs, a five-mutant verification harness, bounded repairs, and PR preparation.
- GitHub Actions that independently reruns tests and mutation verification without AI or model secrets.
Out of scope: six-slot testing matrix, multiple languages/frameworks/browsers, production authentication, real user information, hosting, generic agent orchestration, auto-merging, expensive LLM scoring, elaborate reporting services, and any modification to camiloavilacm/qa-features or its other repositories.

Codex has two distinct roles: (1) infrastructure builder, preparing the app, contracts, validation, skills, and CI; (2) test generator, in a separate, fresh, recorded Codex session after the trusted base is frozen. Do not count infrastructure-stage scaffold code as evidence of generated tests. The actual generation run must start without a completed feature or step definitions available as an answer.
2. Immutable source of truth: SEED-1 behavioral requirement
Supply Codex with requirements/SEED-1.md and the approved technical contracts, not the pre-existing approved Gherkin. Keep the requirement behavioral rather than leaking implementation detail into every scenario.

Story: As a visitor, I want to register and sign in so I can reach my protected account settings.

AC-1 — Register: A new, unique synthetic identity can register. Registration returns the expected user and authentication token; the browser becomes authenticated; /settings displays that identity's email.

AC-2 — Valid login: The immutable seeded baseline user can sign in with valid credentials. Login returns that baseline user and token; the browser becomes authenticated; /settings displays the baseline email.

AC-3 — Invalid password: The baseline user's invalid-password attempt is rejected with the exact required error; the browser remains unauthenticated; direct navigation to /settings is denied and redirects to /login; the login heading is present, and account identity is absent.

Shared setup: before each scenario, seed or verify the same immutable synthetic baseline user and start a fresh browser context with empty cookies, localStorage and sessionStorage. AC-1 must generate a unique email (UUID is fine). Reset the application's data between baseline runs and between mutants; seeded baseline identity is deterministic and never edited or deleted by generated tests.

Do not include language about a “matrix slot” in this standalone project's requirement or Gherkin.

Mutant validity rule: A fault is valid only if it breaks an explicitly specified requirement or technical contract. Do not test duplicate-registration rejection as part of AC-1 unless that separate behavior is explicitly added and approved; it is not an existing AC.
Contract facts verified from qa-features on 2026-11-18
Persist a faithful local copy of the relevant contract data under contracts/ (source provenance in docs), and make the app and generated test interface conform to it. Do not copy the existing approved login.feature into the Codex generation workspace.

API contract:
Behavior	Required contract
API prefix	/api
Registration	POST /api/users → HTTP 201
Valid login	POST /api/users/login → HTTP 200
Invalid credentials	POST /api/users/login → HTTP 422
Authenticated user	GET /api/user → HTTP 200
Missing authentication	GET /api/user → HTTP 401
Authorization header	Authorization: Token <jwt>
Browser token	localStorage under key jwt
Register route	/register
Login route	/login
Protected route	/settings
Unauthenticated redirect	/login
Exact invalid-login UI error	Email or password is invalid.
Invalid-login API body	{"errors":{"email or password":["is invalid"]}}


Registration and successful-login responses contain a user object, the expected email/identity and a token. Define the relevant request and response envelopes unambiguously in the local contract; keep them aligned with the approved Conduit-style format, including a top-level user object. JWT format and the test-only login token can be synthetic, but do not use cookie authentication as a substitute for the specified localStorage JWT behavior. A bare GET /api/user must be checked independently for HTTP 401.

Selectors:
Logical selector	Locator
register.username	label Username
register.email	label Email
register.password	label Password
register.submit	button role, name Sign up
login.email	label Email
login.password	label Password
login.submit	button role, name Sign in
login.error	alert role
login.heading	heading role, name Sign in
account.identity	data-testid="account-email"


Use semantic role/label/test-ID locators; do not replace this contract with an invented all-`data-testid` contract. Keep selectors as an explicit fixture rather than copying the hidden approved Gherkin.

Original source-contract links (for provenance, not to be fetched by Codex during generation):
- API expectations: https://github.com/camiloavilacm/qa-features/blob/main/api-expectations.yaml
- Selectors: https://github.com/camiloavilacm/qa-features/blob/main/selectors.json
- Source feature (post-generation reference only): https://github.com/camiloavilacm/qa-features/blob/main/features/auth/login.feature
The source feature is a held-out reference, not an input prompt or a file in the Codex workspace. Remove any existing reference/login.feature from the generation workspace, and remove draft-generation instructions that ask Codex to diff against it. Do not checkout the upstream repository or retrieve its approved feature from the web during generation. For this version, defer automated golden scoring: review against a small fixed behavior checklist instead.
3. Required user-visible workflow
The repo's README must present a genuinely runnable, human-gated sequence:
1. Prepare: create a feature branch, verify the fixed requirement and local contracts, install dependencies, and confirm the synthetic app can start. Record a SHA-256 digest of the requirement input and contract files.
2. Generate Gherkin: run the actual Codex skill generate-gherkin to produce drafts/SEED-1/login.feature from the requirement/contracts only. Do not pre-fill it from the upstream approved feature.
3. Validate + Gate 1: parse the generated Gherkin; require exactly the known AC-1/AC-2/AC-3 tags, exactly one scenario per AC, no untraced scenarios, and a shared Background. Present a human semantic checklist (registration identity/token/session, login identity/token/session, invalid-error/no-auth/redirect/protected-page denial). A person explicitly approves and commits the exact draft feature, using a recorded SHA-256 approval. AI may not execute or impersonate this operation.
4. Generate steps: run generate-steps only if the approved feature hash matches. Generate pytest-bdd step definitions and Playwright page objects using the approved selectors and supplied fixture interfaces. It must not modify Gherkin, app code, fixtures, validators, mutants, or approval records.
5. Validate: execute the same generated suite against a fresh correct app twice, resetting app state and browser contexts between runs. Run independent API 401 validation. If either baseline fails, stop before mutants.
6. Mutation validation: start the app separately for each of the five faults listed below, reset state, run the targeted generated AC scenario(s), collect trusted fault-branch execution counts, and classify outcomes. All five must be killed for successful completion.
7. Repair, if needed: Codex may adjust generated steps/page objects, at most two repairs, with a logged reason, changed-file diff, and before/after test result. Re-run both baselines and all mutants after each repair. No weakening, skipping or modifying the test oracle. If still failing, stop and expose the failure.
8. Prepare and open PR: produce an evidence-rich PR body and a committed branch. A human expressly authorizes any push or gh pr create. Open the PR before its final GitHub review.
9. Gate 2 — human PR review: human reviewer inspects traceability, actual assertions, mutation evidence, unauthorized diffs and CI checks. Merge is optional and must never happen automatically.
A command-line helper (tools/pipeline.py or similarly small existing tool) may manage state and these transitions. It must fail closed on missing gates and invalid files. A collection of manual CLI commands is acceptable; do not introduce a large agent service.
4. Synthetic application and five targeted faults
The app must implement the contract in section 2 and launch locally with no paid accounts or real credentials. Use the existing small Python HTTP implementation if maintainable, or FastAPI if it materially simplifies robust testing; keep one app and one process per validation case. Application faults must be enabled only by the trusted runner, one at a time. Normal app behavior must be bug-free with all flags off.

Implement the following five faults with deterministic, individually observable behavior:
Fault switch	AC	Deliberately broken behavior	What generated test should notice
BUG_WRONG_REGISTRATION_IDENTITY	AC-1	Successful registration produces the wrong displayed/returned identity	Incorrect registered identity vs unique input
BUG_REJECT_VALID_LOGIN	AC-2	Correct seeded credentials are rejected	Required successful login/session is absent
BUG_ACCEPT_ANY_PASSWORD	AC-3	Baseline email with invalid password is incorrectly accepted	Rejection/error expectation is violated
BUG_SESSION_ON_FAILED_LOGIN	AC-3	UI says login failed but a usable auth token/session is created	Auth state unexpectedly exists (ideally demonstrated by protected access)
BUG_PROTECTED_ROUTE_OPEN	AC-3	Unauthenticated /settings exposes protected content instead of redirecting	Route/identity isolation expectation is violated


Fault instrumentation: Each faulty branch increments a dedicated execution counter only when that branch actually runs, not when its endpoint is entered. Expose trusted counts to the mutation runner using a test-only mechanism (for example, process-private metrics output). Generated tests must never access fault flags, execution counters, internal app stores or mutation configuration. Do not rely on a public debug endpoint to make tests “kill” the mutants. The runner checks counts after the targeted test execution.

Mutant outcome classification (write these fields to JSON and print a compact table):
- killed: app health check passed; relevant faulty branch executed (count > 0); targeted scenario fails because of a meaningful behavioral assertion that the fault violates.
- survived: faulty branch executed, but targeted scenario passes (or fails only for an unrelated reason).
- not_exercised: fault branch count is 0, whether the targeted scenario passes or not.
- invalid: startup, fixture/setup, undefined steps, runner crash, or other infrastructure failure prevents valid measurement.
- inconclusive: timeout or ambiguous failure without sufficient verified assertion evidence.
Only killed contributes to the 5/5 completion target. Do not count any application crash, missing selector, undefined step, or random timeout as a killed mutant. When a test fails, capture a suitable redacted failure reason and the associated target AC. Run only the matching scenario(s) to classify each fault; independent API contract tests must not accidentally serve as the mutant-kill evidence.

Reset policy: each of the two normal baseline executions and each mutant runs against an isolated fresh app state seeded with the same baseline account. Use a fresh Playwright browser context for every scenario. Provide a health check separate from the functional assertions.
5. Generation quality gates and traceability
Structural Gherkin gate
- Parse real Gherkin (prefer an actual parser; a carefully tested minimal parser is acceptable if the supported grammar is explicit).
- Exactly @SEED-1 and @AC-1, @AC-2, @AC-3 for this demo; exactly one scenario mapped to each AC; no untraced scenario.
- Every scenario has meaningful executable steps; reject malformed constructs and duplicate/missing tags.
- Require a seeded baseline/fresh auth-context Background or equivalent documented shared setup.
- Do not confuse structural compliance with behavioral coverage. Gate 1's human checklist explicitly checks all acceptance behaviors.
Generated-step checks
- No undefined/ambiguous pytest-bdd steps.
- No assert True, unconditional failures, pytest.skip, xfail, ignored assertions, fixed sleeps, wait_for_timeout, network stubs that fabricate SUT success, or test logic that reads fault flags/counters.
- Do not require a literal assert statement inside every Then: page-object assertion methods are valid.
- Verify API response status and user/token payload when the approved scenario requires it; verify browser authentication state and protected route through Playwright.
- The generated steps may read only approved API and selector contracts and must not infer unsupported locators or alter application behavior.
- Keep tests independent of ordering, and use UUID-suffixed registration emails.
Traceability report
Emit a machine-readable report mapping AC → scenario → bound step functions → baseline run result → relevant mutant outcomes, plus a concise Markdown/JSON human summary. The report must reflect actual parsed definitions and executed test results, not text guessed by a model. Missing/unbound steps fail validation.
Evidence and redaction
Produce machine-readable baseline/mutation summaries, JUnit XML, and useful Playwright traces on failure (where supported), with Git SHA, requirement/contract/approved-feature hashes, model identifier if available from the real Codex run, skill file hashes, and actual commands. Never leak passwords, raw JWTs, Authorization values, or raw storage snapshots. authorization_present/`jwt_present` booleans are acceptable. Logs, traces and screenshots need safe defaults; do not claim fully automated secret scanning.
6. Gating, change scope and limitations
Approval provenance
Use a clear human-only CLI step for Gate 1 that copies the reviewed draft to features/auth/login.feature and records its SHA-256 in approvals/login.feature.sha256 (optionally companion metadata with requirement/contract digests, timestamp, and Git revision). Explain that the human must review the draft, run the command from their own terminal, and make their own Git commit. Make the step-generation preflight check the hash on every invocation.

Important: A matching hash alone does not authenticate a person. Codex may execute tools with the user's OS identity. Use Codex's supported sandbox and approval settings to reduce write scope; do not assume that AGENTS.md or a skill can enforce a filesystem boundary. The human must execute the approval command outside the agent session and commit the approval artifact. Independently verify generated diffs and protected-file hashes in a deterministic validator and CI. A determined agent with sufficient shell access may bypass workflow instructions; document that limitation. Do not use unrestricted or bypass-approval execution modes for the demo.
Change scopes
There are two distinct policies:

Allowed AI generation/repair edits:
- Before Gate 1: drafts/SEED-1/login.feature only.
- After Gate 1: tests/steps/** and tests/pages/** only.
- No agent writes to the approved .feature or approval files after approval.
Allowed artifacts in the complete human-mediated PR:
- features/auth/login.feature (introduced/approved once).
- approvals/login.feature.sha256 (human-created approval artifact).
- tests/steps/** and tests/pages/** (generated implementation).
- Optional small machine-readable metadata/evidence manifest that is explicitly identified in the allowlist.
Trusted fixtures, contracts, requirements, agent instructions, tools/, app/, .github/ and skills are prepared on the protected base branch, not edited by the generation PR. Add a deterministic PR diff allowlist checker against the merge base and CODEOWNERS for trusted paths. Handle added, modified, deleted, renamed and symlink paths safely. The approval file must be allowed in the PR but must not be an AI-generated edit.

CI caveat: A normal pull_request workflow can execute the PR's own workflow/scripts. CODEOWNERS only enforces review if branch protection/rulesets require code-owner approval. For this educational demo, documented limitations + diff check + code owner review + required CI are sufficient. Do not say CI runs immutable base-branch code unless you actually implement that guarantee. Do not use pull_request_target to checkout and execute untrusted generated code with privileged secrets.
7. Codex-native instructions and two generation skills
Use AGENTS.md for repository-wide constraints and Codex's supported skill mechanism for two reusable tasks. Put skills in .agents/skills/generate-gherkin/SKILL.md and .agents/skills/generate-steps/SKILL.md when supported by the installed Codex version; verify actual skill discovery and invocation in the target environment. Do not assume Claude-style slash commands or settings are portable.

generate-gherkin:
- Inputs: requirements/SEED-1.md, contracts/*, no golden feature.
- Output: only drafts/SEED-1/login.feature.
- Preserve the three AC meanings and all observable behavior; do not assume unprovided behavior.
- Run structural validation, report omissions/ambiguity, and stop for human semantic review/approval.
- Must not approve, edit the app, or generate step code.
generate-steps:
- Preconditions: exact human approval hash matches features/auth/login.feature.
- Inputs: approved feature, contracts, trusted fixture API/docs.
- Output: only tests/steps/** and tests/pages/**.
- Reuse existing step functions where possible and create real pytest-bdd/Playwright assertions.
- Run verification and, if necessary, perform up to two documented repairs limited to generated code.
- Never alter ACs, selectors, fixtures, fault definitions or evidence classifications; never skip tests or suppress failures.
- Stop before any unauthorized push, PR creation, or review.
AGENTS.md should specify stage boundaries, protected files, stop conditions, prohibited shortcuts, and required evidence. Codex's sandbox/approval settings are a supporting control, not a replacement for deterministic scope validation. Do not invent .claude/settings.json, PreToolUse, or Claude slash-command instructions. Provide tested Codex-specific invocation instructions in README; if the local version cannot discover project skills, supply explicit prompts that reference the corresponding SKILL.md files and mark skill-discovery verification as not run.
8. Suggested repository layout
Use the following logical layout. Preserve good existing paths where practical; especially features/auth/login.feature if the starter repo uses it consistently.
qa-ai-generation-pipeline/
├── README.md
├── AGENTS.md
├── requirements/
│   └── SEED-1.md
├── contracts/
│   ├── api-expectations.yaml             # or .json, faithful data
│   └── selectors.json
├── .agents/
│   └── skills/
│       ├── generate-gherkin/SKILL.md
│       └── generate-steps/SKILL.md
├── drafts/SEED-1/                    # draft produced by Codex, not prefilled
├── features/auth/login.feature        # absent until genuine human approval in new demo
├── approvals/login.feature.sha256     # human approval artifact, not prefilled
├── app/                               # trusted synthetic SUT, faults, instrumentation
├── tests/
│   ├── conftest.py                     # trusted fixture interfaces
│   ├── steps/                          # Codex generated
│   ├── pages/                          # Codex generated
│   └── test_contract_and_tools.py      # trusted independent checks
├── tools/
│   ├── pipeline.py                     # small CLI and stage transitions
│   ├── validate_traceability.py
│   ├── validate_scope.py
│   └── run_mutants.py
├── .github/
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── workflows/validate.yml
├── reports/                           # generated, gitignored
├── pyproject.toml                     # or retained requirements-dev.txt
└── .gitignore
Important transition from starter scaffold: If an already committed Gherkin/steps example exists, move it outside the live demonstration's branch/workspace or remove it from the protected starting commit. It may be used to test tooling before the demo, but do not keep a finished golden answer visible to Claude or call preexisting tests “Codex-generated.” Build unit tests of the deterministic validators and mutation harness that do not require the final AI-generated feature to be checked in on the base branch. The demo PR should clearly show newly generated code and a genuinely human-reviewed feature.
9. CI and PR requirements
Use a conventional pull_request GitHub Actions workflow, read-only token permissions, Python 3.12, Playwright Chromium installation, and no model credentials. On a generated PR, run:
1. Scope and approved-hash checks.
2. Gherkin structural traceability validation; fail on undefined steps.
3. Two independent passing baseline executions with full reset.
4. All five mutants, each separately; fail unless exactly five are killed validly.
5. Produce traceability JSON, JUnit XML, mutation JSON and failure traces as downloadable workflow artifacts.
6. Produce a compact summary suitable for the PR description.
For the bootstrap branch, run infrastructure unit/smoke tests only until actual generated feature/steps and human approval artifacts exist; do not mark the generated-scenario pipeline as passed before it exists. Keep branch conditions straightforward and document them. Do not use mock test results to satisfy PR checks.

PR template should include: requirement ID and SHA, model/skill versions if observed, exact approved feature SHA, mapping AC-1/2/3, two baseline outcomes, 5-mutant outcome table with fault-hit counts, repair history, CI run link, changed files, and a human reviewer checklist. The GitHub PR is opened before final PR review. gh CLI is optional to the local validation and requires authentication and explicit user permission; a local PR_BODY.md does not count as an open PR.
10. CLI contract / reproducible demo
Choose a minimal, documented CLI with roughly these human-facing operations (adjust exact names if needed and make README consistent):
# Setup / checks; no Codex invocation is faked
python tools/pipeline.py begin SEED-1

# Human starts a fresh Codex generation session and invokes the generate-gherkin skill (verified local syntax)
python tools/pipeline.py validate-draft SEED-1

# HUMAN ONLY after reading draft and checklist
python tools/pipeline.py approve-gherkin SEED-1
# HUMAN commits approval in Git

# Human starts a fresh Codex generation session and invokes the generate-steps skill (verified local syntax)
python tools/pipeline.py verify SEED-1
# verify = baseline twice + API check + all five mutants + traceability

# Authorized human prepares/pushes branch and opens a real PR
python tools/pipeline.py prepare-pr SEED-1
# gh pr create --base main --head <branch> --body-file <prepared-body>
Human-facing commands must show the current stage and why blocked operations fail. Approval must require an explicit interactive action and should refuse noninteractive calls by default. Creating a PR must never be done silently as a side effect of verification.
11. Tests Codex must write for the pipeline itself
At minimum, write fast deterministic unit/integration tests for:
- Every API route, expected response envelope, JWT storage/authenticated flow and unauthenticated 401.
- Each of the five individual app faults actually changes the required behavior and increments its own branch counter only when exercised.
- Data resets and immutable baseline seeding.
- Gherkin parser: valid three-AC feature, duplicate/missing/unknown AC, untagged scenario, malformed steps.
- Approval: missing receipt, mismatched hash, modified feature after Gate 1, noninteractive approval rejection.
- Diff scope: valid generated changes, forbidden app/tools/contracts changes, attempted modification of approval artifacts by agent, rename/symlink bypasses as feasible.
- Mutation classifications: meaningful target assertion failure + executed branch = killed; target passed = survived; branch not hit = not_exercised; startup/setup failure = invalid; timeout/ambiguous = inconclusive.
- Verify two-baseline prerequisite: fail one baseline and confirm mutants do not run.
- Bounded repair: at most two attempts, approved feature always unchanged, invalid changes rejected.
- Evidence redaction and report schema without exposing test credentials or token values.
Prefer clear integration tests over complicated abstraction layers. Do not count a test of the mutation classifier's mock inputs as a successful live 5/5 mutation demo.
12. Definition of done — distinguish implementation from demonstration
A. Codex infrastructure implementation is done when
- [ ] Repository works independently of qa-features; existing starter assets are reconciled.
- [ ] Requirement and locally verified contracts faithfully define SEED-1 behavior.
- [ ] Synthetic app, baseline fixture and five instrumented mutants exist and pass direct contract/fixture tests.
- [ ] Both Codex generation skills exist with correct inputs, outputs and stop gates.
- [ ] Human approval, hash validation, scope checking, traceability, repeat-baseline, mutation classification, and PR preparation are implemented and tested.
- [ ] CI has separate honest bootstrap and actual-generated-PR checks; no runtime model access or model secrets.
- [ ] README contains runnable setup, exact live demo steps, known limitations, and troubleshooting.
- [ ] No generated scenario, approval, Codex run, live mutant result or PR is falsely represented as completed.
B. The actual requirement #2 demo is done only after
- [ ] Codex really generated Gherkin without the held-out feature in its available workspace/context.
- [ ] A human reviewed all three ACs and committed the approved hash/feature.
- [ ] Codex really generated/adjusted the pytest-bdd/Playwright implementation after approval.
- [ ] Independent fresh baseline A and baseline B both passed.
- [ ] All 5/5 valid, exercised faults were killed by the proper target AC assertions; none counted invalid or inconclusive failures as kills.
- [ ] The approved Gherkin remained byte-identical after approval; repair attempts were bounded and evidenced.
- [ ] GitHub Actions reproduced validation with downloadable artifacts.
- [ ] A real open GitHub PR contains the diff and evidence, and a human performs PR review (merge optional).
13. Preferred execution order for Codex
1. Inspect existing project, note discrepancies against this spec (particularly exposed golden reference, prewritten steps, existing CLI/CI, and missing mutants).
2. Normalize SEED-1 requirement/contracts and implement trustworthy synthetic app + fault instrumentation.
3. Implement/test isolated baseline/mutant runner and classification before relying on AI-generated tests.
4. Implement/test Gherkin parser, approval gating, scope checker and traceability.
5. Implement/refine the two Codex-native skills, project rules, supported sandbox settings, and scope checks.
6. Wire the small orchestration CLI, evidence output, CI and PR template.
7. Run infrastructure tests and whatever generated tests legitimately exist; label unperformed live stages NOT RUN.
8. Update README with concrete instructions and report evidence honestly.
Success criterion for this implementation request: deliver a working, small, inspectable project that a human can hand to Codex to carry out an authentic requirement → Gherkin → approved steps → behavioral verification → PR demonstration. No additional architecture beyond what is needed to prove that flow.