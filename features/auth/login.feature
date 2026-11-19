@SEED-1
Feature: Register and sign in to access account settings
  As a visitor, I want to register and sign in so I can reach my protected account settings.

  Background:
    Given the immutable baseline user is seeded
    And I have a fresh browser context with empty cookies, localStorage, and sessionStorage

  @AC-1
  Scenario: Register a new identity and access its settings
    Given a new synthetic identity with a unique email
    When I submit that identity's registration details on "/register"
    Then the registration response has status 201
    And the response contains a user with the submitted username and email and an authentication token
    And the browser stores the returned token under "jwt" in localStorage
    When I navigate directly to "/settings"
    Then I remain on "/settings"
    And the account identity displays the registered email

  @AC-2
  Scenario: Sign in as the baseline user and access its settings
    When I submit the baseline user's valid credentials on "/login"
    Then the login response has status 200
    And the response contains a user with the baseline username and email and an authentication token
    And the browser stores the returned token under "jwt" in localStorage
    When I navigate directly to "/settings"
    Then I remain on "/settings"
    And the account identity displays the baseline email

  @AC-3
  Scenario: Reject an invalid password and deny access to settings
    When I submit the baseline user's email and an invalid password on "/login"
    Then the login response has status 422
    And the response body is exactly {"errors":{"email or password":["is invalid"]}}
    And the login alert says exactly "Email or password is invalid."
    And cookies, localStorage, and sessionStorage remain empty
    When I navigate directly to "/settings"
    Then I am redirected to "/login"
    And the "Sign in" heading is visible
    And the account identity is absent
