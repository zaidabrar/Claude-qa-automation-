---
mode: agent
description: Triage and fix a failing scenario using the evidence captured on Sauce Labs
---
Scenario `${input:scenario:feature:line, e.g. src/test/resources/features/app_123/login.feature:12}` of ticket `${input:ticket:Jira key}` is failing.

1. If I haven't given you a `run_id`, call `run_on_sauce` for this scenario. Then call `get_failure_evidence` for each failing device.
2. Decide between test defect, product bug, environment, and unclear using the triage rules in `.github/agents/qa-engineer.agent.md`.
3. For a test defect, fix the root cause. Locators must come from the locator inventory. Re-run with `run_on_sauce` using the same `run_id`, for at most 3 rounds.
4. For a product bug, don't touch the test. Show me the evidence and ask whether to call `file_jira_bug`.
