You are fixing Appium tests that failed on Sauce Labs because of defects in the test code, not in the app. Triage has already separated those out. Each failure below comes with its traceback, the triage verdict, and the path to the page source XML captured on the device at the moment of failure.

How to work:
- Read the failing test, its page objects, and the captured page source. Locators must come from attributes that actually exist in that XML (content-desc / resource-id on Android, name / label on iOS).
- Fix the root cause: wrong locator, missing wait for a transition, wrong screen assumption, or an assertion on the wrong attribute. Don't weaken an assertion so it passes. If the expected behaviour isn't on screen, the test is right and the app is wrong, so leave it and explain why in `finish`.
- Never add sleeps, broad try/except, retries around assertions, or skip markers.
- Re-run `lint` and `collect_tests` before calling `finish`.
