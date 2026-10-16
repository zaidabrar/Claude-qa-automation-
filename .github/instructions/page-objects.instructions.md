---
applyTo: "mobile-tests/src/test/java/**/pages/**/*.java"
---
# Page objects

- Package `com.qa.mobile.pages`, one class per screen, extending `BasePage` (which initialises `AppiumFieldDecorator`).
- Declare each element once for both platforms:
  ```java
  @AndroidFindBy(accessibility = "promo-code-input")
  @iOSXCUITFindBy(accessibility = "promo-code-input")
  private WebElement promoCodeInput;
  ```
- Locator preference: `accessibility`, then `id` (Android resource-id) / `iOSNsPredicate` with `name ==`, then `uiAutomator` / `iOSClassChain`. Never absolute XPath.
- If a locator is unconfirmed, add `// TODO(locator): confirm` on the annotation. The self-healing loop replaces it using the page source captured on Sauce Labs.
- Expose intent-level methods (`applyPromoCode(String)`, `totalPrice()`), never raw `WebElement`s. Use `BasePage` helpers `tap`, `type`, `visible`, `isVisible`, and `textOf`, all of which wait explicitly.
- Elements are fields, with no `driver.findElement` in methods except for genuinely dynamic lists.
