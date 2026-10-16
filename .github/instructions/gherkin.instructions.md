---
applyTo: "mobile-tests/**/*.feature"
---
# Feature files

- Location: `src/test/resources/features/<jira_key_lowercase_with_underscores>/<feature_name>.feature`, e.g. `features/app_123/checkout_promo_code.feature`.
- Tag the `Feature:` with the Jira key (`@APP-123`). Tag each scenario with its test-plan case id and priority (`@TC-03 @P1`). Add `@android` or `@ios` only when the scenario applies to one platform. `@example` is reserved for reference examples, which the harness never runs.
- Write in the user's language: `When I apply the promo code "SAVE10"`, not `When I tap the element with id promo_input`.
- Use Given for state, When for the one action under test, and Then for observable outcomes. Each scenario has a single When/Then pair, and repeated setup goes in a `Background`.
- Put data that varies in `Scenario Outline` + `Examples`, and keep literal values in quotes so they bind as `{string}` parameters.
- Every Then must be checkable on screen. Avoid vague outcomes like "it works".
