## SEED-1

- Requirement SHA-256 and contract digests
- Approved feature SHA-256 and Gate 1 commit
- Gherkin and step generation model IDs, if observed
- Skill revision or SHA-256
- Commit under review

## Traceability

| AC | Approved scenario | Bound functions or report |
| --- | --- | --- |
| AC-1 | | |
| AC-2 | | |
| AC-3 | | |

## Local verification

- Baseline A
- Baseline B
- Independent bare current-user API 401

| Fault | AC | Outcome | Branch hits |
| --- | --- | --- | --- |
| BUG_WRONG_REGISTRATION_IDENTITY | AC-1 | | |
| BUG_REJECT_VALID_LOGIN | AC-2 | | |
| BUG_ACCEPT_ANY_PASSWORD | AC-3 | | |
| BUG_SESSION_ON_FAILED_LOGIN | AC-3 | | |
| BUG_PROTECTED_ROUTE_OPEN | AC-3 | | |

## Repair history and changed files

List attempts with reasons, diffs, prior and subsequent outcomes, and changed files.

## Gate 2 · Human review

- CI run and artifact link
- [ ] Compare all three ACs with the approved scenarios and committed approval hash.
- [ ] Inspect actual browser interactions and behavioral assertions.
- [ ] Confirm both baselines passed and every targeted fault was exercised and killed.
- [ ] Confirm only approved and generated paths changed.
- [ ] Review the redacted evidence before sharing.
