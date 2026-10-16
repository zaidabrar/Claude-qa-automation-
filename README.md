# qa-harness: autonomous AI QA for mobile apps

`qa-harness` takes a Jira ticket and delivers a review-ready pull request of **Appium Java + TestNG + Cucumber**
tests that have already run on **Sauce Labs real devices**, without a person in the loop. Engineers working
in **GitHub Copilot** get the same capabilities interactively, through custom instructions, prompt files, and an
MCP server ([docs/copilot.md](docs/copilot.md)).

```
Jira ticket ──► test plan ──► .feature + steps + page objects ──► Sauce Labs device matrix ──► triage
                (traceable     (team conventions, compiled,          (parallel; screenshot,      │
                 to AC)         Cucumber dry-run clean)                page source, device +      ├─ test defect ─► self-heal ─► re-run
                                                                       Appium logs)               ├─ environment ─► retry once
                                                                                                  ├─ product bug ─► Jira bug (+evidence, linked)
                                                                                                  └─ unclear ────► flagged for a human
                                          ──► branch + draft PR (scenario × device matrix, coverage, Sauce links)
                                          ──► Jira comment + transition + label ──► Slack
```

## What it does

| Stage | What happens |
|---|---|
| **Ingest** | Pulls the ticket from Jira REST v3, including description, acceptance criteria (from a section or a custom field), comments, and linked issues. |
| **Plan** | Claude writes a structured test plan. Every case traces to acceptance criteria and covers happy, negative, edge, regression, and accessibility paths in proportion to risk, phrased so the steps become Gherkin. Ambiguities are stated as assumptions, not blockers. |
| **Generate** | An agent reads the team conventions (the same files Copilot uses) and the existing suite. It then writes `features/<ticket>/*.feature`, step definitions, and `@AndroidFindBy`/`@iOSXCUITFindBy` page objects, reusing existing steps. It runs `mvn test-compile` and a Cucumber dry run until every step is defined and unambiguous. |
| **Execute** | Compiles once, then runs `surefire:test` on every Sauce Labs device in parallel, selecting exact scenarios by `feature:line`. App binaries are uploaded once. Each failure captures a screenshot and page source, and the device and Appium logs are downloaded from Sauce. |
| **Triage** | Claude classifies each failure as `test_defect`, `product_bug`, `environment`, or `needs_human`. It reads the screenshot (vision), page source, failing step, Java stack trace, crash lines in device logs, cross-device patterns, and flake history. |
| **Heal** | Test defects go back to an agent that fixes locators and waits from the *real* page source. It may not weaken assertions, sleep, or skip. All of the ticket's scenarios are re-verified on affected devices. Bounded by `max_heal_attempts`. |
| **Bugs** | High-confidence product bugs become Jira bugs with repro steps, the violated criteria, evidence, screenshots, and Sauce session links, linked to the source ticket. |
| **Publish** | Creates branch `qa/<key>-<summary>`, commits, pushes, and opens a draft PR. The PR body holds a scenario × device matrix linking each cell to its Sauce video, plan coverage, assumptions, and the cost. |
| **Report** | Posts a Jira comment, transitions the ticket (pass/fail), adds a `qa-ai-done` label, and sends a Slack message. |

### Built for unattended operation
- **Autonomy modes:** `autonomous` (no prompts), `supervised` (confirm each external write in the terminal), and `dry_run` (tests still run on Sauce, but nothing is written to Jira or GitHub). Every side effect goes through one gate and is recorded in `audit.jsonl`.
- **Checkpoint/resume:** `qa-harness resume <run_id>` continues after a crash or budget stop.
- **Hard cost cap:** `llm.max_usd_per_run` is enforced before every model call.
- **Sandboxed agent:** agents can read the repo, but not `.env`, keys, or `.git`. They can write only `.java`, `.feature`, and resource files inside `mobile-tests/`, and never `pom.xml`, since dependency changes need a human.
- **Fail closed:** a scenario that didn't run (bad id, crash, compile error) is reported as an error, never a pass. Bugs are filed only above `min_bug_confidence`. The harness refuses to run over uncommitted test changes.
- **Claude API best practices:** Claude Opus 5.5 with adaptive thinking and per-stage effort, schema-validated structured outputs, validated streaming tool inputs, prompt caching, append-only history, explicit `refusal`/`max_tokens` handling, and server-side refusal fallbacks.

## Quick start

Requirements: Python 3.10+, JDK 17+, Maven 3.9+.

```bash
pip install -e '.[mcp]'
cp qa_harness.example.yaml qa_harness.yaml    # Jira URL, devices, app, autonomy (commit this)
cp .env.example .env && $EDITOR .env          # credentials (never committed)
set -a && . ./.env && set +a

qa-harness doctor                      # config, credentials, JDK/Maven, Jira + Sauce connectivity
qa-harness plan APP-123                # just the test plan
qa-harness --mode dry_run run APP-123  # full run, no Jira/GitHub writes
qa-harness run APP-123                 # full autonomous run
qa-harness watch                       # daemon: process every ticket matching jira.ready_jql
```

Without Jira, pass a ticket as JSON (fields from `qa_harness.models.Ticket`):
`qa-harness run APP-123 --ticket-file ticket.json`.

Exit codes for CI are: `0` passed, `2` product bug found, `3` needs a human, `4` still failing, `1` error.

### The test project by hand

```bash
cd mobile-tests
mvn test-compile surefire:test -Dcucumber.execution.dry-run=true       # bind all steps, no device
QA_DEVICE='{"name":"pixel","platform":"android","device_name":"Google Pixel.*"}' \
QA_APP_ANDROID=storage:filename=MyApp.apk \
mvn test -Dcucumber.filter.tags="@APP-123"                              # run on Sauce Labs
APPIUM_URL=http://127.0.0.1:4723 mvn test -Dcucumber.features=src/test/resources/features/app_123/login.feature:12
```

## GitHub Copilot

| File | Purpose |
|---|---|
| `.github/copilot-instructions.md` | Repo-wide rules: architecture of the test project, golden rules, how to verify |
| `.github/instructions/*.instructions.md` | Path-specific rules for `.feature` files, step definitions, and page objects |
| `.github/prompts/*.prompt.md` | `/automate-ticket`, `/heal-scenario`, `/hand-off-to-qa-agent` |
| `.vscode/mcp.json` | Registers the `qa-harness` MCP server: Jira, Cucumber dry-run, Sauce Labs runs, autonomous hand-off |
| `.github/workflows/copilot-setup-steps.yml` | JDK + Maven + harness for Copilot coding agent |

See [docs/copilot.md](docs/copilot.md) for setup in VS Code, IntelliJ, and the Copilot coding agent.

## Running it hands-free

`.github/workflows/qa-agent.yml` gives you three triggers:

1. **Jira Automation (recommended):** create a rule *"When issue transitioned to Ready for QA → Send web request"*:
   `POST https://api.github.com/repos/<owner>/<repo>/dispatches`, header `Authorization: Bearer <token>`,
   body `{"event_type": "qa-ticket", "client_payload": {"ticket": "{{issue.key}}"}}`.
2. **Schedule:** sweeps `jira.ready_jql` every two hours on weekdays.
3. **Manual:** Actions → qa-agent → Run workflow.

Repository secrets: `ANTHROPIC_API_KEY`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`, plus
optional `SLACK_WEBHOOK_URL` and `QA_BOT_TOKEN`. PRs opened with the default `GITHUB_TOKEN` don't trigger other
workflows, so use a PAT or GitHub App token if CI must run on agent PRs.

## Configuring the app under test

- `sauce.android_app` / `sauce.ios_app` take either a local `.apk/.aab/.ipa` path (uploaded to Sauce storage each
  run) or an existing reference such as `storage:filename=MyApp.apk`.
- `sauce.devices[].device_name` accepts a regex (`"Google Pixel.*"`) so Sauce can pick any free matching device.
- If the app needs a private backend, start Sauce Connect and set `SAUCE_TUNNEL_NAME`.
- For a private Maven repository, set `project.maven_args: ["-s", "path/to/settings.xml"]`.

## Layout

```
mobile-tests/                      Maven project: Appium java-client 9, TestNG 7, Cucumber 7
  src/test/java/com/qa/mobile/
    runners/RunCucumberTest        TestNG runner (+ QaResultsPlugin for the harness)
    hooks/Hooks                    platform skip, failure evidence, Sauce job result, teardown
    support/                       TestContext (lazy driver), DriverFactory, DeviceConfig, QaResultsPlugin
    pages/  steps/                 page objects and step definitions (agent writes here)
  src/test/resources/features/     one folder per Jira ticket
src/qa_harness/
  cli.py  pipeline.py  llm.py  tools.py  state.py  framework.py (Maven/Cucumber adapter)  mcp_server.py
  stages/ planner, generator, executor, triage (+heal, bug drafting), reporter
  integrations/ jira (REST v3 + ADF), saucelabs, github (+git), notify (Slack)
  prompts/                         stage prompts
.github/                           Copilot instructions + prompt files, CI, agent and Copilot setup workflows
tests/                             harness tests incl. a real Maven/Cucumber contract test
```

See [docs/architecture.md](docs/architecture.md) for the design and extension points.

## Development

```bash
pip install -e '.[dev]'
ruff check src tests && pytest tests      # the contract test needs JDK + Maven (skipped otherwise)
```
