# qa-harness: autonomous AI QA for mobile apps

`qa-harness` takes a Jira ticket and delivers a review-ready pull request of Appium tests that have
already run on Sauce Labs real devices, without a person in the loop.

```
Jira ticket ──► test plan ──► Appium tests ──► Sauce Labs device matrix ──► triage
                (traceable    (page objects,    (parallel, evidence:        │
                 to AC)        lint+collect      screenshot, page source,   ├─ test defect ─► self-heal ─► re-run
                               verified)         device + Appium logs)      ├─ environment ─► retry once
                                                                            ├─ product bug ─► Jira bug (+evidence, linked)
                                                                            └─ unclear ────► flagged for a human
                                                   ──► branch + PR (device matrix, coverage, Sauce links)
                                                   ──► Jira comment + transition + label ──► Slack
```

## What it does

| Stage | What happens |
|---|---|
| **Ingest** | Pulls the ticket from Jira REST v3, including description, acceptance criteria (from a section or a custom field), comments, and linked issues. |
| **Plan** | Claude writes a structured test plan. Every case traces to acceptance criteria and covers happy, negative, edge, regression, and accessibility paths in proportion to risk. Non-automatable cases are flagged with a reason. Ambiguities are stated as assumptions, not blockers. |
| **Generate** | A tool-using agent explores the existing suite, then writes page objects and tests that follow `mobile_tests/CONVENTIONS.md`. It verifies its own work with `ruff` and `pytest --collect-only` before finishing. |
| **Execute** | The suite runs on every configured Sauce Labs device in parallel. App binaries are uploaded once per run. Each failure captures a screenshot and page source, and the device and Appium logs are downloaded from Sauce. |
| **Triage** | Claude classifies each failure as `test_defect`, `product_bug`, `environment`, or `needs_human`. It reads the screenshot (vision), page source, crash lines from device logs, cross-device patterns, and per-test flake history. |
| **Heal** | Test defects go back to an agent that fixes locators and waits from the *real* page source. It may not weaken assertions, sleep, or skip. The whole ticket suite is re-verified on affected devices. Bounded by `max_heal_attempts`. |
| **Bugs** | High-confidence product bugs become Jira bugs with repro steps, the violated criteria, evidence, screenshots, and Sauce session links, linked to the source ticket. |
| **Publish** | Creates a branch `qa/<key>-<summary>`, commits, pushes, and opens a draft PR. The PR body holds a device × test matrix linking each cell to its Sauce video, the plan coverage, assumptions, and the cost. |
| **Report** | Posts a Jira comment, transitions the ticket (pass/fail), adds a `qa-ai-done` label, and sends a Slack message. |

### Built for unattended operation
- **Autonomy modes:** `autonomous` (no prompts), `supervised` (confirm each external write in the terminal), and `dry_run` (tests still run on Sauce, but nothing is written to Jira or GitHub). Every side effect goes through one gate and is recorded in `audit.jsonl`.
- **Checkpoint/resume:** each stage checkpoints to `.qa_runs/<run_id>/state.json`, and `qa-harness resume <run_id>` continues after a crash or budget stop.
- **Hard cost cap:** `llm.max_usd_per_run` is enforced before every model call. Cost is reported in the PR and the state file.
- **Sandboxed agent:** agents can read the repo, but not `.env`, keys, or `.git`, and can write only inside `mobile_tests/`. Pytest invocations from the agent can't pass flags or load plugins.
- **Safety rails on autonomy:** bugs are filed only above `min_bug_confidence`. Self-healing and environment retries are bounded. The harness refuses to run over uncommitted changes in the tests directory. A test that never ran is reported as an error, never as a pass.
- **Claude API best practices:** Claude Opus 5.5 with adaptive thinking and per-stage effort, schema-validated structured outputs, validated streaming tool inputs, prompt caching, append-only history, explicit `refusal`/`max_tokens` handling, and server-side refusal fallbacks (`fallbacks: "default"`).

## Quick start

```bash
pip install -e '.[mobile]'
cp qa_harness.example.yaml qa_harness.yaml    # Jira URL, devices, app, autonomy (commit this)
cp .env.example .env && $EDITOR .env          # credentials (never committed)
set -a && . ./.env && set +a

qa-harness doctor                    # checks config, credentials, Jira + Sauce connectivity
qa-harness plan APP-123              # just the test plan
qa-harness --mode dry_run run APP-123  # full run, no Jira/GitHub writes
qa-harness run APP-123               # full autonomous run
qa-harness watch                     # daemon: process every ticket matching jira.ready_jql
```

Without Jira, pass a ticket as JSON (fields from `qa_harness.models.Ticket`):
`qa-harness run APP-123 --ticket-file ticket.json`.

Exit codes for CI are: `0` passed, `2` product bug found, `3` needs a human, `4` still failing, `1` error.

## Running it hands-free

`.github/workflows/qa-agent.yml` gives you three triggers:

1. **Jira Automation (recommended):** create a rule *"When issue transitioned to Ready for QA → Send web request"*:
   `POST https://api.github.com/repos/<owner>/<repo>/dispatches`, header `Authorization: Bearer <token>`,
   body `{"event_type": "qa-ticket", "client_payload": {"ticket": "{{issue.key}}"}}`.
2. **Schedule:** sweeps `jira.ready_jql` every two hours on weekdays.
3. **Manual:** Actions → qa-agent → Run workflow.

Repository secrets: `ANTHROPIC_API_KEY`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY`, plus
optional `SLACK_WEBHOOK_URL` and `QA_BOT_TOKEN`. PRs opened with the default `GITHUB_TOKEN` don't trigger other
workflows, so use a PAT or GitHub App token if your CI must run on agent PRs.

From Claude Code you can also run `/qa-ticket APP-123 dry_run`.

## Configuring the app under test

- `sauce.android_app` / `sauce.ios_app` take either a local `.apk/.aab/.ipa` path (uploaded to Sauce storage each run)
  or an existing reference such as `storage:filename=MyApp.apk`. In CI, upload the build from your app pipeline first
  and reference it by filename.
- `sauce.devices[].device_name` accepts a regex (`"Google Pixel.*"`) so Sauce can pick any free matching device.
- If the app needs a private backend, start Sauce Connect and set `SAUCE_TUNNEL_NAME`.

## Steering the agent

- `mobile_tests/CONVENTIONS.md` is the agent's style guide. Edit it, and generated code follows.
- `src/qa_harness/prompts/*.md` hold the stage instructions (planning, generation, healing, triage, bug writing).
- Ask for stronger analysis with `llm.effort: xhigh`, or reduce spend with `medium`.

## Layout

```
src/qa_harness/
  cli.py           commands: run | resume | watch | plan | report | doctor
  pipeline.py      stage orchestration, heal/retry loop, bug filing, PR, Jira report
  llm.py           Claude wrapper: structured outputs, agent loop, budget, refusals, fallbacks
  tools.py         sandboxed agent tools (read/search/write/edit/lint/collect)
  state.py         checkpoints, audit log, autonomy gate, flake memory
  stages/          planner, generator, executor (Sauce), triage (+heal, bug drafting), reporter
  integrations/    jira (REST v3 + ADF), saucelabs, github (+git), notify (Slack)
  prompts/         stage prompts
mobile_tests/      Appium + pytest suite the agent writes into (conftest: Sauce sessions, evidence capture)
tests/             harness tests: unit + end-to-end pipeline scenarios with fakes and a real git remote
```

See [docs/architecture.md](docs/architecture.md) for the design and extension points.

## Development

```bash
pip install -e '.[dev,mobile]'
ruff check src tests mobile_tests && pytest tests
```
