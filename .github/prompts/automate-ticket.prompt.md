---
mode: agent
description: Turn a Jira ticket into Cucumber scenarios, steps and page objects, then validate them on Sauce Labs
---
Automate Jira ticket `${input:ticket:Jira key, e.g. APP-123}` in `mobile-tests/`.

1. Fetch the ticket with the `get_jira_ticket` tool of the `qa-harness` MCP server. To get a traceable plan first, call `plan_tests`.
2. Read the existing step definitions and page objects before writing, then reuse and extend them.
3. Write the feature file, any missing step definitions, and page objects following the repository instructions. Cover each acceptance criterion with at least one scenario, plus the negative and edge cases that carry real risk.
4. Call `discover_scenarios` with the new feature file until it compiles and has no undefined or ambiguous steps.
5. Call `run_on_sauce` with the scenario ids. For each failure, open the returned `page_source` file and fix locators from attributes that actually exist. If the app itself violates the ticket, keep the test and tell me it found a bug, with the evidence.
6. Finish with a summary table of scenario × device results, including Sauce links.
