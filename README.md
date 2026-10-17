# qa-harness: autonomous mobile QA with GitHub Copilot

Give GitHub Copilot a Jira ticket. It writes the **Appium Java + TestNG + Cucumber** scenarios, runs them on
**Sauce Labs real devices**, triages and fixes failures, files real bugs in Jira, reports back to the ticket, and
opens the pull request.

**No LLM key.** Copilot, under your existing licence, is the agent. This repo provides the agent profile, the
team conventions, and an MCP toolbox (`qa-harness`) for everything an editor can't do on its own. The only
credentials are Jira and Sauce Labs, plus an optional GitHub token.

```
              ┌──────────── GitHub Copilot (the brain) ────────────┐
 Jira ticket  │  .github/agents/qa-engineer.agent.md  (workflow)   │
 ───────────► │  .github/copilot-instructions.md + instructions/   │
              │     (team conventions)                             │
              │  plans · writes code · triages · fixes             │
              └───────────────┬────────────────────────────────────┘
                              │ MCP tools (qa-harness, no LLM)
   ┌──────────────┬───────────┼──────────────┬──────────────────┬──────────────┐
   ▼              ▼           ▼              ▼                  ▼              ▼
 Jira         Maven +      Sauce Labs     failure evidence   Jira bug +     git + PR
 ticket       Cucumber     device matrix  (locator inventory, report +      (branch, draft
              dry run      (parallel)     crash logs, hints) transition     PR, matrix)
```

## The loop Copilot runs (`qa-engineer` agent)

1. `jira_get_ticket`: reads the acceptance criteria, then plans scenarios (happy, negative, and edge cases in proportion to risk).
2. Writes `features/<ticket>/*.feature`, step definitions, and page objects, reusing existing steps.
3. `discover_scenarios`: compiles and dry-runs Cucumber until no step is undefined or ambiguous.
4. `run_on_sauce`: runs every scenario on every configured device in parallel. It returns a `run_id`, Sauce video links, and a first-guess hint for each failure.
5. `get_failure_evidence` for each failure: the error, the failing step, the stack trace, a **locator inventory** condensed from the page source, crash lines from device logs, results on the other devices, and flake history. Copilot then decides:
   - **test defect:** fix it from the real locators and re-run with the same `run_id`, for at most 3 rounds;
   - **product bug:** `file_jira_bug`, which adds screenshots, Sauce links, and a link to the ticket;
   - **environment / unclear:** re-run once, otherwise flag it for a human.
6. `publish_results_to_jira` comments the report, moves the ticket to pass or fail, and labels it.
7. `open_pull_request` commits only `mobile-tests/`, pushes a `qa/<ticket>` branch, and opens a draft PR with a scenario × device matrix. The Copilot coding agent instead uses `get_pr_description` for the PR it opens itself.

### Guardrails enforced in code, whatever the agent says
- A bug can be filed only for a scenario that is **failing in the recorded Sauce Labs results**, and only once.
- Pass/fail in Jira and the PR comes from **recorded results**, never from the agent's summary.
- Only files under `mobile-tests/` are committed. Other local edits are left alone.
- A scenario that didn't run (bad id, compile error, crash) is recorded as an **error**, never a pass.
- `autonomy.mode: dry_run` logs every Jira or GitHub write and skips it. VS Code also asks before each tool call unless you auto-approve.
- Every run keeps `run.json` and `audit.jsonl` under `.qa_runs/<ticket>-<timestamp>/`, together with the screenshots, page sources, and logs.

## Three ways to use it

| | How | Autonomy |
|---|---|---|
| **VS Code / IntelliJ, Copilot agent mode** | `/automate-ticket APP-123`, `/heal-scenario`, `/qa-sweep` | Autonomous inside the IDE. You see each step and approve tool calls. |
| **Copilot coding agent** | Assign a "[QA] APP-123" issue to Copilot | Fully unattended in GitHub's cloud. Copilot opens the PR. |
| **Jira → Copilot, hands-free** | `.github/workflows/jira-to-copilot.yml`: a Jira Automation webhook or a schedule creates the issue and assigns Copilot | Zero-touch from "Ready for QA" to PR |

Setup for each is in [docs/copilot.md](docs/copilot.md).

## Quick start (VS Code)

Requirements: Python 3.10+, JDK 17+, Maven 3.9+, and a GitHub Copilot licence.

```bash
pip install -e .
cp qa_harness.example.yaml qa_harness.yaml    # Jira URL, devices, app (commit this)
cp .env.example .env && $EDITOR .env          # Jira + Sauce Labs credentials (never committed)
set -a && . ./.env && set +a && qa-harness doctor
```

Open the folder in VS Code. `.vscode/mcp.json` registers the `qa-harness` server, so start it when prompted. Then in
Copilot Chat, in **Agent** mode, run `/automate-ticket` and enter a Jira key.

### The same tools from the command line

```bash
qa-harness ready                                         # tickets waiting for QA
qa-harness ticket APP-123                                # ticket as markdown
qa-harness discover mobile-tests/src/test/resources/features/app_123/login.feature
qa-harness run APP-123 -s src/test/resources/features/app_123/login.feature:5
qa-harness evidence <run_id> <feature:line> <device>
qa-harness publish APP-123     # Jira report for the latest run
qa-harness pr APP-123          # commit tests, push, open draft PR
```

### The test project directly

```bash
cd mobile-tests
mvn test-compile surefire:test -Dcucumber.execution.dry-run=true       # bind all steps, no device
QA_DEVICE='{"name":"pixel","platform":"android","device_name":"Google Pixel.*"}' \
QA_APP_ANDROID=storage:filename=MyApp.apk mvn test -Dcucumber.filter.tags="@APP-123"
APPIUM_URL=http://127.0.0.1:4723 mvn test -Dcucumber.features=src/test/resources/features/app_123/login.feature:5
```

## Configuring the app under test
- `sauce.android_app` / `sauce.ios_app` take a local `.apk/.aab/.ipa` (uploaded once per run) or `storage:filename=MyApp.apk`.
- `sauce.devices[].device_name` accepts a regex (`"Google Pixel.*"`) so Sauce can pick any free matching device.
- If the app needs a private backend, start Sauce Connect and set `SAUCE_TUNNEL_NAME`.
- For a private Maven repository, set `project.maven_args: ["-s", "path/to/settings.xml"]`.

## Layout

```
.github/
  agents/qa-engineer.agent.md         the autonomous QA workflow + triage and fix rules (Copilot custom agent)
  copilot-instructions.md             repo-wide conventions
  instructions/*.instructions.md      rules for .feature files, step definitions, page objects
  prompts/*.prompt.md                 /automate-ticket  /heal-scenario  /qa-sweep
  workflows/                          ci · jira-to-copilot · copilot-setup-steps
.vscode/mcp.json                      registers the qa-harness MCP server
mobile-tests/                         Maven: Appium java-client 9, TestNG 7, Cucumber 7
  src/test/java/com/qa/mobile/        runners · hooks · support (TestContext, DriverFactory, QaResultsPlugin) · pages · steps
  src/test/resources/features/        one folder per Jira ticket
src/qa_harness/                       MCP toolbox (no LLM)
  mcp_server.py  cli.py  ops.py       tools → operations (guardrails live in ops.py)
  executor.py  framework.py           Sauce Labs runs (parallel per device) · Maven/Cucumber adapter
  evidence.py  report.py  state.py    locator inventory + hints · reports · run records, audit, flake memory
  integrations/                       jira (REST v3 + ADF) · saucelabs · github + git · slack
tests/                                harness tests, including a real Maven/Cucumber contract test
```

## Development

```bash
pip install -e '.[dev]'
ruff check src tests && pytest tests      # the contract test needs JDK + Maven (skipped otherwise)
```
