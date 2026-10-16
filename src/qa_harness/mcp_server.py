"""MCP server exposing the harness to GitHub Copilot agent mode (or any MCP client).

Copilot does the interactive authoring in the IDE; these tools give it what it cannot
do alone: read the Jira ticket, validate Cucumber glue, run scenarios on Sauce Labs
real devices with evidence for healing, and hand a ticket to the autonomous pipeline.

Configured in .vscode/mcp.json:  qa-harness --config qa_harness.yaml mcp
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .config import AutonomyMode, Secrets, Settings
from .integrations.jira import JiraClient
from .integrations.saucelabs import SauceClient
from .models import Outcome
from .stages.executor import SauceExecutor
from .stages.planner import render_ticket
from .stages.reporter import render_report
from .state import RunState

INSTRUCTIONS = """\
Tools for the mobile QA workflow in this repository (Appium Java + TestNG + Cucumber on Sauce Labs).
Typical loop: get_jira_ticket -> write the feature, steps, and page objects -> discover_scenarios until clean
-> run_on_sauce -> on failure, read the returned page_source file and fix locators from real attributes -> re-run.
Use start_autonomous_run to hand a whole ticket to the autonomous pipeline instead."""


def build_server(settings: Settings) -> MCPServer:
    # Imported here so `qa-harness` works without the MCP extra unless this command is used.
    from .cli import build_framework

    server = MCPServer("qa-harness", instructions=INSTRUCTIONS)
    secrets = Secrets.from_env(settings.notify)
    framework = build_framework(settings)

    def jira() -> JiraClient:
        if not (settings.jira.base_url and secrets.jira_email and secrets.jira_token):
            raise RuntimeError("Jira is not configured: set jira.base_url, JIRA_EMAIL and JIRA_API_TOKEN")
        return JiraClient(settings.jira, secrets.jira_email, secrets.jira_token)

    @server.tool()
    def get_jira_ticket(ticket_key: str) -> str:
        """Fetch a Jira ticket: summary, description, acceptance criteria, comments, and links."""
        return render_ticket(jira().get_ticket(ticket_key))

    @server.tool()
    def list_devices() -> str:
        """List the Sauce Labs device matrix configured in qa_harness.yaml."""
        return (
            "\n".join(
                f"- {d.name}: {d.platform} {d.platform_version} {d.device_name!r} ({'real' if d.real_device else 'vm'})"
                for d in settings.sauce.devices
            )
            or "No devices configured (sauce.devices)."
        )

    @server.tool()
    def discover_scenarios(feature_files: list[str] | None = None) -> str:
        """Compile the test project and Cucumber dry-run the given feature files (repo-relative paths; empty
        means the whole suite). Returns scenario ids (feature:line) and any undefined or ambiguous steps."""
        features = [framework.to_project_path(f) or f for f in (feature_files or [])]
        return framework.discover(features or None).summary()

    @server.tool()
    def run_on_sauce(scenario_ids: list[str], devices: list[str] | None = None) -> str:
        """Run scenarios (ids from discover_scenarios, e.g.
        src/test/resources/features/app_123/login.feature:12) on Sauce Labs real devices.
        Returns per-device results, Sauce video links, and for failures the failing step, the error, and the
        paths of the captured screenshot and page source XML to use when fixing locators."""
        if not (secrets.sauce_username and secrets.sauce_access_key):
            return "Sauce Labs is not configured: set SAUCE_USERNAME and SAUCE_ACCESS_KEY."
        names = devices or [d.name for d in settings.sauce.devices]
        unknown = set(names) - {d.name for d in settings.sauce.devices}
        if unknown:
            return f"Unknown device(s): {', '.join(sorted(unknown))}. Use list_devices."
        run_dir = settings.runs_root / f"copilot-{time.strftime('%Y%m%dT%H%M%S')}"
        sauce = SauceClient(settings.sauce, secrets.sauce_username, secrets.sauce_access_key)
        executor = SauceExecutor(settings, secrets, sauce, framework, run_dir)
        summary = executor.run({n: list(scenario_ids) for n in names}, 1, f"copilot-{run_dir.name}")

        lines = [f"Results ({summary.counts()}), artifacts in {_rel(run_dir, settings)}:"]
        for r in summary.results:
            lines.append(f"- {r.outcome.value.upper()} {r.name or r.node_id} on {r.device} {r.sauce_url or ''}")
            if r.outcome in (Outcome.failed, Outcome.error):
                lines.append(f"  error: {r.message[:1500]}")
                for name, path in r.artifacts.items():
                    lines.append(f"  {name}: {_rel(Path(path), settings)}")
        return "\n".join(lines)

    @server.tool()
    def plan_tests(ticket_key: str) -> str:
        """Use Claude to draft a test plan for a ticket, with every case traced to acceptance criteria.
        Requires ANTHROPIC_API_KEY."""
        from .llm import LLM
        from .stages.planner import build_plan

        plan = build_plan(LLM(settings.llm), jira().get_ticket(ticket_key), settings)
        return plan.model_dump_json(indent=2)

    @server.tool()
    def start_autonomous_run(ticket_key: str, mode: str = "dry_run") -> str:
        """Hand a ticket to the autonomous pipeline: plan, generate, run on Sauce Labs, triage and self-heal,
        file bugs, open a PR, and update Jira. mode is 'dry_run' (no Jira/GitHub writes) or 'autonomous'.
        Runs in the background; poll with get_run_status."""
        if mode not in (AutonomyMode.dry_run.value, AutonomyMode.autonomous.value):
            return "mode must be 'dry_run' or 'autonomous'"
        settings.runs_root.mkdir(parents=True, exist_ok=True)
        log = settings.runs_root / f"{ticket_key}-mcp.log"
        subprocess.Popen(
            [sys.executable, "-m", "qa_harness.cli", "--mode", mode, "run", ticket_key],
            cwd=settings.repo_root,
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return f"Started {ticket_key} in {mode} mode. Log: {_rel(log, settings)}. Poll get_run_status('{ticket_key}')."

    @server.tool()
    def get_run_status(ticket_key: str) -> str:
        """Status and report of the latest pipeline run for a ticket."""
        runs = sorted(settings.runs_root.glob(f"{ticket_key}-*/state.json"), key=lambda p: p.stat().st_mtime)
        if not runs:
            return f"No runs found for {ticket_key}."
        state = RunState.model_validate_json(runs[-1].read_text())
        head = f"Run {state.run_id}: {state.status}; stages done: {', '.join(state.completed_stages) or 'none'}"
        if state.error:
            head += f"\nError: {state.error}"
        return head + "\n\n" + render_report(state)

    return server


def _rel(path: Path, settings: Settings) -> str:
    try:
        return str(path.resolve().relative_to(settings.repo_root))
    except ValueError:
        return str(path)


def serve(settings: Settings) -> None:
    build_server(settings).run("stdio")
