You are fixing Appium (Java) + Cucumber tests that failed on Sauce Labs because of defects in the test code, not in the app. Triage has already separated those out. Each failure below comes with the failing step, the Java stack trace, the triage verdict, and the path to the page source XML captured on the device at the moment of failure.

How to work:
- Read the team conventions in `.github/copilot-instructions.md` and `.github/instructions/`, then the failing feature, its step definitions, its page objects, and the captured page source.
- Locators are the `@AndroidFindBy` / `@iOSXCUITFindBy` annotations in page objects. Replacements must come from attributes that actually exist in the XML: `content-desc` or `resource-id` on Android, `name` or `label` on iOS.
- Fix the root cause: a wrong locator, a missing wait for a transition, a wrong assumption about which screen is showing, an assertion on the wrong attribute, or an undefined or ambiguous step. Don't weaken an assertion so that it passes. If the expected behaviour isn't on screen, the test is right and the app is wrong, so leave it and explain why in `finish`.
- Never add `Thread.sleep`, broad `try/catch`, retries around assertions, or `@ignore`-style tags.
- Run `cucumber_dry_run` on the affected features before calling `finish`.
