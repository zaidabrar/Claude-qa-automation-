# Setting up GitHub Copilot

Copilot is the agent, and this repo gives it the workflow, the conventions, and the tools. No LLM API key is involved.

| Piece | File | Used by |
|---|---|---|
| QA agent profile (workflow, triage and fix rules) | `.github/agents/qa-engineer.agent.md` | VS Code agent mode, Copilot coding agent |
| Team conventions | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` | Chat, agent mode, coding agent, code review |
| Prompt files | `.github/prompts/*.prompt.md` | VS Code / JetBrains Copilot Chat |
| MCP toolbox | `qa-harness mcp` (`.vscode/mcp.json`) | VS Code agent mode, coding agent |
| Coding agent environment | `.github/workflows/copilot-setup-steps.yml` | Copilot coding agent |
| Jira → Copilot dispatcher | `.github/workflows/jira-to-copilot.yml` | Hands-free mode |

## 1. VS Code (agent mode)

1. `pip install -e .`, copy `qa_harness.example.yaml` to `qa_harness.yaml`, and fill `.env` from `.env.example`
   (Jira + Sauce Labs).
2. Open the repo. `.vscode/mcp.json` registers the `qa-harness` server and loads `.env`. Start it from the MCP
   view, or accept the prompt, then check that its 11 tools appear in the agent's tool picker.
3. Open Copilot Chat, choose **Agent** mode (or select the `qa-engineer` agent if your VS Code lists custom
   agents), and run:
   - `/automate-ticket` for the full flow on one ticket;
   - `/heal-scenario` to triage and fix one failing scenario;
   - `/qa-sweep` to process every ticket in `jira.ready_jql`.
4. VS Code asks before each tool call. For a hands-off run, auto-approve the read and run tools
   (`jira_get_ticket`, `discover_scenarios`, `run_on_sauce`, `get_failure_evidence`, ...) and keep approval on the
   writes (`file_jira_bug`, `publish_results_to_jira`, `open_pull_request`). Set `autonomy.mode: dry_run` while
   you evaluate.

**JetBrains (IntelliJ):** add an MCP server in the Copilot settings with command `qa-harness`, args
`--config <repo>/qa_harness.yaml mcp`, and the same environment variables. Prompt files and instructions are
picked up from `.github/`.

## 2. Copilot coding agent (unattended, in GitHub's cloud)

1. `copilot-setup-steps.yml` already installs the JDK, warms the Maven cache, and installs `qa-harness`.
2. In the repository, go to **Settings → Copilot → Coding agent → MCP configuration** and add:

```json
{
  "mcpServers": {
    "qa-harness": {
      "type": "local",
      "command": "qa-harness",
      "args": ["--config", "qa_harness.yaml", "mcp"],
      "tools": ["*"],
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

3. Create those `COPILOT_MCP_*` secrets in the repository's **copilot** environment.
4. Allow outbound access to your Jira site, `api.<region>.saucelabs.com` and `ondemand.<region>.saucelabs.com` in
   the coding agent's firewall settings, if the firewall is enabled.
5. Assign an issue such as *"[QA] APP-123: automate and validate on Sauce Labs"* to Copilot. It follows
   `qa-engineer.agent.md`, so it runs on Sauce Labs, files bugs, reports to Jira, and opens a PR whose description
   comes from `get_pr_description`.

Check the exact screen names and JSON fields against GitHub's current Copilot coding agent docs, since GitHub
revises this area often.

## 3. Hands-free: Jira → Copilot

`.github/workflows/jira-to-copilot.yml` turns Jira tickets into issues assigned to the Copilot coding agent:

- **Jira Automation** (recommended): use the rule *When issue transitioned to Ready for QA → Send web request*,
  with `POST https://api.github.com/repos/<owner>/<repo>/dispatches`, header `Authorization: Bearer <PAT>`, and body
  `{"event_type": "qa-ticket", "client_payload": {"ticket": "{{issue.key}}"}}`.
- **Schedule:** sweeps `jira.ready_jql` every two hours on weekdays.
- **Manual:** Actions → jira-to-copilot → Run workflow.

Secrets: `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `QA_BOT_TOKEN` (a user fine-grained PAT with Issues: write, which
assigning Copilot requires). If assignment fails, the workflow warns, and you can assign Copilot to the issue by
hand. The workflow skips tickets that already have an open "[QA] KEY" issue.

## 4. Copilot code review

Code review reads `.github/copilot-instructions.md` too, so every PR (from people or from Copilot) is reviewed
against the same rules: no sleeps, no absolute XPath, no weakened assertions, and steps reused rather than
duplicated.
