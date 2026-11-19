---
name: generate-gherkin
description: Draft the SEED-1 login feature from its written requirement and local contracts, then stop for human review.
---

Work from the repository root in the draft stage defined by AGENTS.md. Read
`requirements/SEED-1.md` and `contracts/*.json`. Use those inputs alone for
behavior. Do not retrieve any upstream feature, existing solution, or reference.

Write only `drafts/SEED-1/login.feature`. Use the English Gherkin subset
accepted by the structural gate. Include the `@SEED-1` feature tag, a shared
Background for baseline verification and fresh auth state, and one plain
scenario each with `@AC-1`, `@AC-2`, and `@AC-3`. Represent every observable
acceptance behavior, including rejection, empty authentication state and
direct protected-route denial. Keep test data synthetic and out of the feature.

Run `python tools/pipeline.py validate-draft SEED-1`. Report the draft path,
hash and any unresolved semantics. Stop at Gate 1. The owner reviews and
commits the feature and receipt from their own terminal.
