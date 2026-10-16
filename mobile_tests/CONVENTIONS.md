# Mobile test conventions

The QA agent reads this file before writing or fixing tests. Edit it to steer generated code.

## Layout
- `pages/` holds page objects, one class per screen, subclassing `BasePage`.
- `tests/` holds pytest modules named `test_<jira_key_lower>_<feature>.py`, e.g. `test_app_123_checkout.py`.
- Reuse an existing page object before creating a new one. Extend it with new locators/methods rather than duplicating.

## Tests
- Every test takes the `driver` fixture and carries `@pytest.mark.ticket("KEY")`, `@pytest.mark.case("TC-xx")` and `@pytest.mark.priority(n)` from the test plan.
- Platform-specific tests add `@pytest.mark.platform("android")` or `("ios")`.
- One behaviour per test. Arrange via page-object methods, then assert on observable UI state with a clear message.
- No `time.sleep`. Use the `BasePage` explicit waits.
- No raw `driver.find_element` in tests. All locators live in page objects.
- Test data is defined at the top of the module as constants, never inline magic strings.

## Locators (most to least preferred)
1. Accessibility id (`AppiumBy.ACCESSIBILITY_ID`)
2. Resource id on Android (`AppiumBy.ID`) / name on iOS
3. `-android uiautomator` / `-ios predicate string`
4. Relative XPath anchored on a stable attribute. Never absolute XPath.

When a locator is unknown, mark it `# TODO(locator): confirm` and pick the most likely accessibility id from the ticket wording. The self-healing loop fixes it from the real page source captured on Sauce Labs.
