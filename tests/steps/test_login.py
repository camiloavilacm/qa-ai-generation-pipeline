from pytest_bdd import given, scenarios, then, when

from tests.pages.auth import AuthPage


scenarios("login.feature")


@given("the immutable baseline user is seeded")
def seeded_baseline(page, baseline_user):
    """Use the trusted baseline and browser setup."""


@given("I have a fresh browser context with empty cookies, localStorage, and sessionStorage")
def fresh_browser_context(page):
    """Use the trusted page fixture's fresh-context checks."""


@given("a new synthetic identity with a unique email")
def unique_registration_identity(registration_user):
    """Provision the scenario-scoped synthetic identity from the trusted fixture."""


def endpoint(base_url, api_contract, request_name):
    return f"{base_url.rstrip('/')}{api_contract['api_prefix']}{api_contract['checks'][request_name]['path']}"


@when('I submit that identity\'s registration details on "/register"', target_fixture="generated_submission")
def submit_registration(page, base_url, api_contract, registration_user):
    return AuthPage(page).register(
        endpoint(base_url, api_contract, "register"),
        registration_user.username,
        registration_user.email,
        registration_user.password,
    )


@when('I submit the baseline user\'s valid credentials on "/login"', target_fixture="generated_submission")
def submit_valid_login(page, base_url, api_contract, baseline_user):
    return AuthPage(page).sign_in(
        endpoint(base_url, api_contract, "login"),
        baseline_user.email,
        baseline_user.password,
    )


@when('I submit the baseline user\'s email and an invalid password on "/login"', target_fixture="generated_submission")
def submit_invalid_login(page, base_url, api_contract, baseline_user, invalid_password):
    return AuthPage(page).sign_in(
        endpoint(base_url, api_contract, "invalid_login"),
        baseline_user.email,
        invalid_password,
    )


@then("the registration response has status 201")
@then("the login response has status 200")
def successful_response_status(check):
    check("success_response")


def assert_user_response(response, identity):
    user = response.json()["user"]
    identity_matches = user["username"] == identity.username and user["email"] == identity.email
    token_present = isinstance(user.get("token"), str) and bool(user["token"])
    assert identity_matches, "The response user does not match the expected identity"
    assert token_present, "The response user has no authentication token"


@then("the response contains a user with the submitted username and email and an authentication token")
def registration_response_user(generated_submission, registration_user):
    assert_user_response(generated_submission, registration_user)


@then("the response contains a user with the baseline username and email and an authentication token")
def login_response_user(generated_submission, baseline_user):
    assert_user_response(generated_submission, baseline_user)


@then('the browser stores the returned token under "jwt" in localStorage')
def browser_is_authenticated(check):
    check("authenticated")


@when('I navigate directly to "/settings"')
def navigate_to_settings(page):
    page.goto("/settings")


@then('I remain on "/settings"')
def browser_remains_on_settings(page, base_url, api_contract):
    settings_url = f"{base_url.rstrip('/')}{api_contract['ui']['protected_route']}"
    on_settings = page.url == settings_url
    assert on_settings, "The browser left the settings route"


@then("the account identity displays the registered email")
@then("the account identity displays the baseline email")
def settings_shows_identity(check):
    check("settings_identity")


@then("the login response has status 422")
def invalid_login_response_status(check):
    check("invalid_response")


@then('the response body is exactly {"errors":{"email or password":["is invalid"]}}')
def invalid_login_response_body(generated_submission, api_contract):
    expected = api_contract["checks"]["invalid_login"]["body"]
    matches = generated_submission.json() == expected
    assert matches, "The invalid login response does not match the error contract"


@then('the login alert says exactly "Email or password is invalid."')
def login_alert_matches(check):
    check("invalid_message")


@then("cookies, localStorage, and sessionStorage remain empty")
def browser_is_unauthenticated(check):
    check("no_auth")


@then('I am redirected to "/login"')
def browser_redirects_to_login(check):
    check("protected_redirect")


@then('the "Sign in" heading is visible')
def sign_in_heading_is_visible(page):
    heading_is_visible = AuthPage(page).sign_in_heading_is_visible()
    assert heading_is_visible, "The sign-in heading is hidden"


@then("the account identity is absent")
def account_identity_is_absent(check):
    check("identity_absent")
