@example @EXAMPLE-1
Feature: Login (reference example)
  Shows the conventions generated features follow. Excluded from harness runs by the @example tag.

  Background:
    Given the login screen is displayed

  @TC-01 @P1
  Scenario: Wrong password shows an error
    When I log in as "standard_user" with password "wrong-password"
    Then I see a login error containing "invalid"
