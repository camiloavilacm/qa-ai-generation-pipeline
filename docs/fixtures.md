# Generating the pytest-bdd suite

Use `scenarios("login.feature")` in a module named `tests/steps/test_*.py`.
Pytest resolves the feature in `features/auth/`. Define every Given, When and
Then once, including the Background. Place browser page objects in
`tests/pages/` and import them as `tests.pages.<module>`. Target fixtures, if
used, must have names starting with `generated_`.

| Trusted fixture | Interface |
| --- | --- |
| `page` | Playwright sync Page with the app base URL and a fresh context. The harness verifies the seeded account via health and checks for empty cookies, localStorage and sessionStorage before the first step. |
| `base_url` | Loopback origin for the current app process. Use relative paths when supported. |
| `baseline_user` | Immutable `.username`, `.email`, `.password`. |
| `registration_user` | Fresh UUID-based synthetic `.username`, `.email`, `.password` for AC-1. |
| `invalid_password` | The deliberately incorrect synthetic password for AC-3. |
| `api_contract` | Parsed `contracts/api-expectations.json`. |
| `check` | Callable for a named behavioral assertion in a Then step. It reads actual browser activity and raises on error. |

The Background must express shared setup. Request `page` and `baseline_user`
in its binding to use the trusted setup. For each submission, navigate
through the approved page, fill the semantic label locators, and click the
contract button. Synchronize on the real POST response with
`page.expect_response(lambda response: response.url == target_url)` around
the click. A When should only perform
the action and wait for the response. Put status, contents, and UI
expectations in the Then bindings so the same action works across app cases.

## Required Then checks

Each named check must run once for its AC. Place them in the steps matching
the approved scenario's assertions. Extra read-only assertions can use
Playwright `expect` or plain Python.

| AC | `check` argument | Assertion |
| --- | --- | --- |
| AC-1, AC-2 | `success_response` | Observed POST status, expected user and nonempty token in the response. |
| AC-1, AC-2 | `authenticated` | Browser stored the issued token and it authenticates a real current-user request with the right identity. |
| AC-1, AC-2 | `settings_identity` | Protected settings displays the expected email. |
| AC-3 | `invalid_response` | Observed POST returns 422 and the exact error envelope. |
| AC-3 | `invalid_message` | Visible alert matches the exact UI error. |
| AC-3 | `no_auth` | Rejected browser has no cookies and both storage areas are empty. |
| AC-3 | `protected_redirect` | A browser navigation to settings after the submission redirects to the visible sign-in heading. |
| AC-3 | `identity_absent` | The account identity element is absent after the direct-navigation check. |

Check the invalid response and browser state before navigating directly to
settings with `page.goto("/settings")`. The final two AC-3 assertions must
follow that navigation. Credentials come from fixtures. Keep their values,
response tokens and raw storage out of logs and test titles.

The harness maps parsed feature lines to the real pytest-bdd functions
collected for each AC. It attributes a kill only to a matching, trusted
behavioral assertion with a confirmed fault-branch hit. A browser action
timeout or another unclassified failure cannot establish a kill.
