# Architecture

## Split of responsibilities

| | GitHub Copilot (agent) | qa-harness (MCP toolbox, no LLM) |
|---|---|---|
| Understanding | Reads the ticket, plans scenarios, makes assumptions | Fetches the ticket (Jira REST v3, ADF → text, acceptance criteria) |
| Authoring | Writes features, steps, page objects | Compiles, dry-runs Cucumber, reports undefined/ambiguous steps |
| Execution | Decides what to run | Uploads the app once, runs each device in parallel on Sauce Labs, captures evidence |
| Triage | Decides test defect / product bug / environment | Condenses evidence: locator inventory, crash lines, cross-device results, flake history, heuristic hint |
| Fixing | Edits code from the evidence | Re-runs within the same run (attempts are grouped) |
| Reporting | Writes the human summary | Computes status from recorded results; Jira comment, transition, label; bug creation with attachments and links; draft PR |

The rule behind the split: **judgement goes to the agent, facts and side effects go to code.** Anything that must
hold whatever the agent concludes is enforced in `ops.py`:
- bugs only for scenarios that are failing in the recorded results, and once per scenario;
- status always computed from the recorded results;
- commits restricted to `mobile-tests/`;
- dry-run gating of every external write.

## Modules

```
mcp_server.py   11 MCP tools, thin wrappers that return errors as text the agent can act on
cli.py          the same operations for humans/CI (doctor, ready, ticket, discover, run, evidence, report, publish, pr)
ops.py          the operations and their guardrails
services.py     builds Jira / Sauce / git / GitHub clients from config + env (missing creds → None)
framework.py    Maven + Cucumber adapter: compile, dry-run discovery, concurrent surefire:test per device
executor.py     Sauce Labs execution: compile once, parallel devices, results + evidence download
evidence.py     locator inventory from page source, log crash excerpts, deterministic failure hints
report.py       markdown report: scenario × device matrix with Sauce links, failures, bugs
state.py        QaRun records, RunStore (run.json + audit.jsonl), Guard (dry-run), FlakeMemory
integrations/   jira.py · saucelabs.py · github.py (git + REST) · notify.py (Slack)
```

## Run records

```
.qa_runs/<KEY>-<timestamp>/
  run.json        scenario ids, devices, every attempt's results, bugs filed, PR url
  audit.jsonl     each attempt and each Jira/GitHub write (or why it was skipped)
  attempt<N>/<device>/
    run.log, surefire-reports/, results.json
    evidence/<scenario>/screenshot.png, page_source.xml
    sauce/<job_id>/device_log.log, appium_log.log
.qa_runs/flake_memory.json   per scenario@device outcome history across runs
```

`run_on_sauce` with an existing `run_id` appends an attempt. The latest result per (scenario, device) is the
current state.

## Contract between the harness and the test project

The harness compiles `mobile-tests/` once, then runs
`mvn surefire:test -Dcucumber.features=<feature:line,...>` once per device, concurrently. Scenario ids are
`<feature path relative to mobile-tests>:<line>`. The device is described through these environment variables:

| Variable | Meaning |
|---|---|
| `QA_DEVICE` | JSON `DeviceConfig` (name, platform, device_name, platform_version, extra_capabilities) |
| `QA_APP_ANDROID` / `QA_APP_IOS` | Appium `app` capability (`storage:...`) |
| `QA_BUILD` | Sauce build name, so the devices of one attempt group together |
| `QA_RESULTS_FILE` | where `QaResultsPlugin` writes the per-scenario JSON results |
| `QA_ARTIFACTS_DIR` | where `Hooks` saves the screenshot and page source on failure |
| `SAUCE_REGION`, `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`, `SAUCE_TUNNEL_NAME` | Sauce session settings |
| `APPIUM_URL` | bypasses Sauce and targets a local Appium server |

A different stack (Gradle, JUnit 5, WebdriverIO) needs a new `TestFramework` adapter in `framework.py` and a
results reporter that writes the same JSON.
