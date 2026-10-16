# Using the harness with GitHub Copilot

The team writes and reviews tests in the IDE with GitHub Copilot, while the harness runs the same workflow
unattended in CI. Both follow **one set of conventions** and share **one set of tools**:

| | Interactive (engineer + Copilot) | Autonomous (qa-harness in CI) |
|---|---|---|
| Conventions | `.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` (applied by Copilot automatically) | The generator and healer agents are told to read the same files |
| Jira | `get_jira_ticket` MCP tool | Jira REST, automatic |
| Validate glue | `discover_scenarios` MCP tool | `cucumber_dry_run` agent tool |
| Run on devices | `run_on_sauce` MCP tool | Executor, every configured device |
| Fix failures | `/heal-scenario` prompt + page source from `run_on_sauce` | Triage + self-heal loop |
| Ship | You open the PR | Draft PR + Jira update |

Edit the instruction files when the team's conventions change, and both Copilot and the autonomous agent follow.

## 1. Copilot Chat in VS Code / IntelliJ (agent mode)

1. `pip install -e '.[mcp]'`, copy `qa_harness.example.yaml` to `qa_harness.yaml`, and fill `.env` from `.env.example`.
2. Open the repo in VS Code. `.vscode/mcp.json` registers the `qa-harness` MCP server (`qa-harness mcp`) and
   loads credentials from `.env`. Start it from the MCP view, or accept the prompt.
   *IntelliJ: add the same server in Copilot → MCP settings (`command: qa-harness`,
   `args: ["--config", "<repo>/qa_harness.yaml", "mcp"]`, plus the env vars).*
3. In Copilot Chat, switch to **Agent** mode and run one of the prompt files:
   - `/automate-ticket` goes from ticket to feature, steps, and page objects, then dry-runs and runs on Sauce Labs, fixing from page source.
   - `/heal-scenario` fixes a failing scenario from the device's real page source.
   - `/hand-off-to-qa-agent` passes a ticket to the autonomous pipeline and reports back.

MCP tools: `get_jira_ticket`, `plan_tests` (Claude test plan; needs `ANTHROPIC_API_KEY`), `list_devices`,
`discover_scenarios`, `run_on_sauce`, `start_autonomous_run`, `get_run_status`.

## 2. Copilot coding agent (assign an issue to Copilot)

`.github/workflows/copilot-setup-steps.yml` installs the JDK, warms the Maven cache, and installs `qa-harness`
in Copilot's environment. To let it run scenarios on Sauce Labs, go to **Settings → Copilot → Coding agent → MCP
configuration** and add:

```json
{
  "mcpServers": {
    "qa-harness": {
      "type": "local",
      "command": "qa-harness",
      "args": ["--config", "qa_harness.yaml", "mcp"],
      "tools": ["get_jira_ticket", "list_devices", "discover_scenarios", "run_on_sauce"],
      "env": {
        "JIRA_EMAIL": "COPILOT_MCP_JIRA_EMAIL",
        "JIRA_API_TOKEN": "COPILOT_MCP_JIRA_API_TOKEN",
        "SAUCE_USERNAME": "COPILOT_MCP_SAUCE_USERNAME",
        "SAUCE_ACCESS_KEY": "COPILOT_MCP_SAUCE_ACCESS_KEY"
      }
    }
  }
}
```

and create the `COPILOT_MCP_*` secrets in the repository's `copilot` environment. Then an issue such as
*"Automate APP-123 with /automate-ticket"* assigned to Copilot produces a PR whose scenarios have already run
on real devices.

## 3. Copilot code review

Copilot code review reads `.github/copilot-instructions.md` too, so agent-authored PRs (from either engine) are
reviewed against the same rules: no sleeps, no absolute XPath, no weakened assertions, and steps reused rather
than duplicated.

## Which engine for what

- **Copilot (interactive):** exploratory automation, tricky screens, and reviewing and adjusting generated tests.
  The engineer stays in the loop.
- **qa-harness (autonomous, Claude):** the steady flow of "Ready for QA" tickets, unattended, with triage, bug
  filing, a cost cap, and an audit log. Triggered by Jira Automation or a schedule.
