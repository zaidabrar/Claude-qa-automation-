# Repository instructions

This repository holds mobile acceptance tests and the QA toolbox that GitHub Copilot uses to write, run, and maintain them.

- `mobile-tests/` is a Maven project: **Appium Java client 9 + TestNG + Cucumber 7**, run on **Sauce Labs real devices**. Java 17.
- `src/qa_harness/` is the `qa-harness` MCP server, with tools for Jira, compile and dry-run, Sauce Labs runs, failure evidence, bug filing, Jira reporting, and the PR. It contains no LLM, because Copilot is the agent. The end-to-end workflow is in `.github/agents/qa-engineer.agent.md`.

## Architecture of the test project
- `com.qa.mobile.support.TestContext` is per-scenario state injected by cucumber-picocontainer. Get the driver with `ctx.driver()`. The Appium session starts lazily on first use and is quit by `Hooks`.
- `com.qa.mobile.hooks.Hooks` skips `@android`/`@ios` scenarios on the other platform, captures a screenshot and page source on failure, and reports the job result to Sauce. Don't duplicate any of this in steps.
- `com.qa.mobile.support.QaResultsPlugin` writes machine-readable results for the harness. Don't remove it from the runner.
- `com.qa.mobile.runners.RunCucumberTest` is the only runner. Narrow runs with `-Dcucumber.features=path/x.feature:LINE` or `-Dcucumber.filter.tags=...`.
- Devices and apps come from environment variables set by the harness (`QA_DEVICE`, `QA_APP_ANDROID`, `QA_APP_IOS`, `SAUCE_*`), so never hard-code capabilities. Set `APPIUM_URL` to debug against a local Appium server.

## Golden rules
- One behaviour per scenario. Scenarios describe user intent; Java code holds the UI mechanics.
- Reuse before writing: search for an existing step or page object before adding one. Duplicate step patterns fail as ambiguous.
- No `Thread.sleep`, implicit waits, or raw `driver.findElement` in steps. Use `BasePage` helpers and explicit waits.
- No absolute XPath. Locators, from most to least preferred: accessibility id, resource-id / name, UiAutomator / iOS predicate.
- Never weaken an assertion to make a test pass. If the app is wrong, the test should fail.
- Build files (`pom.xml`) change only with a human decision.

## Verifying changes
- Compile and bind steps without a device: the `discover_scenarios` MCP tool, or `mvn -q test-compile surefire:test -Dcucumber.execution.dry-run=true` in `mobile-tests/`.
- Run on real devices: the `run_on_sauce` MCP tool, then `get_failure_evidence` for each failure.
- Never claim a scenario passes without a `run_on_sauce` result showing it.
