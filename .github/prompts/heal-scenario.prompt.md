---
mode: agent
description: Fix a failing Cucumber scenario using the page source captured on Sauce Labs
---
Fix the failing scenario `${input:scenario:feature path:line, e.g. src/test/resources/features/app_123/login.feature:12}`.

1. Run it with `run_on_sauce` (unless I've already given you the failure) and read the failing step, the stack trace, and the captured `page_source` XML.
2. Decide whether the test is wrong (locator, wait, wrong screen, wrong attribute) or the app is wrong. If the app is wrong, stop and explain the evidence. Don't change the test.
3. Fix test defects at the root. Locators must come from attributes present in the page source. No sleeps, no retries around assertions, no weakened assertions.
4. Re-run with `discover_scenarios`, then `run_on_sauce`, until it passes on every configured device.
