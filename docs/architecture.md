# Architecture

## Design choices

**Code owns the workflow, and the model owns judgement.** The pipeline is a fixed, checkpointed state machine
(`pipeline.py`). Claude is used only where judgement is needed: planning, writing tests, triaging, healing, and
writing bugs. Control flow, retries, budgets, and every side effect stay in deterministic code, which makes runs
reproducible, resumable, and auditable.

**Two ways to call the model** (`llm.py`):
- `structured()` makes one call that returns a pydantic model. The planner, triage, and bug writer use it, and
  the schema is enforced by the API (`output_format`), so the pipeline never parses free text.
- `run_agent()` is a tool loop for open-ended work (generation, healing). It ends only when the model calls
  `finish` with a schema-valid result. Tool inputs stream eagerly and are validated before execution. A tool call
  truncated by `max_tokens` is never executed, and a declined request (`refusal`) raises rather than being read
  as output.

**Trust evidence over claims.** After generation, the harness trusts the files actually written and the scenario
ids a Cucumber dry run actually discovers, not the model's own report. During triage, the page source captured on the device is
the primary evidence. During healing, locators must come from attributes present in that XML.

**Fail closed.** If a requested test produces no result (import error, crash, timeout), it is recorded as an
`error`. An unclassified failure becomes `needs_human`. Bugs are filed only above a confidence threshold.

## Run lifecycle

```
ingest → plan → generate → execute ⟲ (triage → heal | retry) → publish (bugs, commit, push, PR) → report (Jira, Slack)
```

`execute` loops until one of these holds:
- every test passes;
- the only remaining failures are product bugs or need a human;
- the heal and retry budgets (`max_heal_attempts`, `max_env_retries`) are used up.

Final status is:
- `passed`: every test passed on every device;
- `product_bug`: only product bugs remain open;
- `needs_human`: failures are mixed, unclassified, or a persistent environment problem;
- `failed`: test defects remained after healing;
- `error`: the run crashed or hit its budget, and is resumable.

## Run directory

```
.qa_runs/<KEY>-<timestamp>/
  state.json      full checkpoint: ticket, plan, generation, every attempt, triage, bugs, PR, cost
  audit.jsonl     every stage, tool call, LLM usage update, and side effect (or why it was skipped)
  plan.json       the test plan
  report.md       the final report (also the PR body)
  artifacts/attempt<N>/<device>/
    run.log, surefire-reports/, results.json
    evidence/<test>/screenshot.png, page_source.xml
    sauce/<job_id>/device_log.log, appium_log.log, ...
.qa_runs/flake_memory.json   per test@device outcome history across runs
```

## Contract between the harness and the suite

The harness compiles the Maven project once, then runs `mvn surefire:test -Dcucumber.features=<feature:line,...>`
once per device (concurrently), describing the device in environment variables. Scenario ids are
`<feature path relative to mobile-tests>:<line>`. Any suite that honours this contract works:

| Variable | Meaning |
|---|---|
| `QA_DEVICE` | JSON `DeviceConfig` (name, platform, device_name, platform_version, extra_capabilities) |
| `QA_APP_ANDROID` / `QA_APP_IOS` | Appium `app` capability (`storage:...`) |
| `QA_BUILD` | Sauce build name, so all devices of a run group together |
| `QA_RESULTS_FILE` | where to write the JSON results list (`TestResult` fields; written by `QaResultsPlugin`) |
| `QA_ARTIFACTS_DIR` | where to save screenshots and page source on failure |
| `SAUCE_REGION`, `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`, `SAUCE_TUNNEL_NAME` | Sauce session settings |
| `APPIUM_URL` | bypasses Sauce and targets a local Appium server, for debugging |

`QaResultsPlugin`, `Hooks`, `DriverFactory`, and `DeviceConfig` in `mobile-tests/` implement it for Appium Java +
Cucumber. Another stack (Gradle, JUnit 5, WebdriverIO) needs a new `TestFramework` adapter in `framework.py`.

## Extension points

- **Another device cloud** (BrowserStack, LambdaTest, a device farm): implement the `Executor` protocol
  (`devices()`, `run(targets, attempt, build)`) and swap it into `Deps`.
- **Another tracker** (Linear, Azure Boards): provide a `load_ticket` callable, and an object with
  `comment/transition/add_label/create_bug/attach/link`.
- **Web or API tests:** change `tests_dir`, the `.github/instructions/` files, and the generator and healer prompts, and keep
  the pipeline.
- **More autonomy controls:** every external write goes through `Guard.run(action, detail, fn)`, so a new policy
  (Slack approval, an allow-list of projects) is a change in one class.
