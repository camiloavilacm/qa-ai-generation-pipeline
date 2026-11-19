# SEED-1 · Register and sign in

As a visitor, I want to register and sign in so I can reach my protected account settings.

- **AC-1 · Register.** A new, unique synthetic identity can register. Registration returns the expected user and an authentication token. The browser becomes authenticated and account settings display the registered email.
- **AC-2 · Valid login.** The immutable seeded baseline user can sign in with valid credentials. Login returns that user and a token. The browser becomes authenticated and account settings display the baseline email.
- **AC-3 · Invalid password.** The baseline user's invalid-password attempt returns the specified rejection and shows the exact error. The browser remains unauthenticated. Direct navigation to settings is denied and redirects to login, where the sign-in heading is visible and the account identity is absent.

Before every scenario, verify the same immutable baseline user is seeded and use a fresh browser context with empty cookies, localStorage and sessionStorage. Use a new, unique synthetic email for registration. Each baseline and fault run starts with fresh app data. Generated tests must never edit or delete the baseline user.

The local API and selector contracts define the observable technical details. The standalone API verification also checks that a bare current-user request returns 401.
