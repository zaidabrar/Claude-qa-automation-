"""MCP server: the QA toolbox GitHub Copilot drives (VS Code agent mode, or the Copilot coding agent).

Copilot is the brain: it plans, writes the Cucumber scenarios and Java glue, triages failures and
fixes tests. These tools are its hands for what an editor cannot do: Jira, compiling and binding
the suite, Sauce Labs real devices, failure evidence, bug filing, reporting, and the pull request.

    qa-harness --config qa_harness.yaml mcp      (registered in .vscode/mcp.json)
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from mcp.server.mcpserver import MCPServer

from . import ops
from .config import Settings
from .models import BugReport
from .services import Services
from .state import RunStore

INSTRUCTIONS = """\
QA toolbox for this repository (Appium Java + TestNG + Cucumber on Sauce Labs). Workflow:
1. jira_get_ticket → plan scenarios from the acceptance criteria.
2. Write the feature, steps, and page objects → discover_scenarios until there are 0 problems.
3. run_on_sauce(ticket_key, scenario_ids) → note the run_id.
4. For each failure, get_failure_evidence → decide: test defect (fix, then run_on_sauce with the same run_id),
   environment (re-run once), or product bug (file_jira_bug).
5. publish_results_to_jira and open_pull_request (or get_pr_description when the platform opens the PR).
Results, statuses, and bug eligibility are taken from the recorded Sauce Labs runs, never from claims."""


def _safe(fn: Callable[..., str]) -> Callable[..., str]:
    """Return errors as text so the agent can read them and adapt."""

    @wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
            return f"Error: {exc}"

    return wrapper


def build_server(settings: Settings, services: Services | None = None) -> MCPServer:
    svc = services or Services.from_settings(settings)
    server = MCPServer("qa-harness", instructions=INSTRUCTIONS)

    @server.tool()
    @_safe
    def qa_ready_tickets(limit: int = 20) -> str:
        """List Jira tickets waiting for QA automation (jira.ready_jql, excluding ones already done)."""
        return ops.ready_tickets(svc, limit)

    @server.tool()
    @_safe
    def jira_get_ticket(ticket_key: str) -> str:
        """Fetch a Jira ticket: summary, description, acceptance criteria, comments, and linked issues."""
        return ops.get_ticket(svc, ticket_key)

    @server.tool()
    @_safe
    def list_devices() -> str:
        """The Sauce Labs device matrix configured for this repo."""
        return ops.list_devices(svc)

    @server.tool()
    @_safe
    def discover_scenarios(feature_files: list[str] | None = None) -> str:
        """Compile the test project and Cucumber dry-run the given feature files (repo-relative; empty means
        all). Returns scenario ids (feature:line) and every undefined or ambiguous step. Uses no device."""
        return ops.discover(svc, feature_files)

    @server.tool()
    @_safe
    def run_on_sauce(
        ticket_key: str, scenario_ids: list[str], devices: list[str] | None = None, run_id: str | None = None
    ) -> str:
        """Run scenarios on Sauce Labs real devices (all configured devices unless `devices` is given).
        Pass the previous run_id when re-running after a fix so attempts are grouped. Returns results with
        Sauce video links and a first-guess hint for each failure."""
        return ops.run_scenarios(svc, ticket_key, scenario_ids, devices, run_id)[1]

    @server.tool()
    @_safe
    def get_failure_evidence(run_id: str, scenario_id: str, device: str) -> str:
        """Everything needed to triage one failure: error, failing step, stack trace, the locator inventory
        from the page source at failure, crash lines from device logs, other devices, and flake history."""
        return ops.failure_evidence(svc, run_id, scenario_id, device)

    @server.tool()
    @_safe
    def file_jira_bug(
        run_id: str,
        scenario_id: str,
        title: str,
        severity: str,
        steps_to_reproduce: list[str],
        expected: str,
        actual: str,
        violated_criteria: list[str] | None = None,
        evidence: list[str] | None = None,
    ) -> str:
        """File a product bug for a scenario that is failing in the recorded run. The bug gets screenshots,
        Sauce Labs session links, device list, and a link to the source ticket. Severity is one of
        Blocker, Critical, Major, Minor, Trivial. Only for app defects, never for test defects."""
        bug = BugReport(
            title=title,
            severity=severity,
            steps_to_reproduce=steps_to_reproduce,
            expected=expected,
            actual=actual,
            violated_criteria=violated_criteria or [],
            evidence=evidence or [],
        )
        return ops.file_bug(svc, run_id, scenario_id, bug)

    @server.tool()
    @_safe
    def publish_results_to_jira(run_id: str) -> str:
        """Comment the run report on the Jira ticket, transition it by the recorded result (pass/fail), and add
        the done label."""
        return ops.publish_to_jira(svc, run_id)

    @server.tool()
    @_safe
    def get_pr_description(run_id: str) -> str:
        """Markdown PR description for a run: scenario × device matrix with Sauce links, failures, bugs."""
        return ops.pr_description(svc, run_id)

    @server.tool()
    @_safe
    def open_pull_request(run_id: str, title: str | None = None) -> str:
        """Commit the changes under the test project to a QA branch, push, and open a draft PR whose description
        is the run report. Not needed in the Copilot coding agent, which opens its own PR (use
        get_pr_description there)."""
        return ops.open_pull_request(svc, run_id, title)

    @server.tool()
    @_safe
    def get_run_report(ticket_key_or_run_id: str) -> str:
        """Report for a run id, or for the latest run of a ticket key."""
        run_id = ticket_key_or_run_id
        if not (settings.runs_root / run_id / "run.json").exists():
            run_id = RunStore.latest_id(settings.runs_root, ticket_key_or_run_id) or ""
        if not run_id:
            return f"No runs found for {ticket_key_or_run_id}."
        return f"run_id: {run_id}\n\n" + ops.pr_description(svc, run_id)

    return server


def serve(settings: Settings) -> None:
    build_server(settings).run("stdio")
