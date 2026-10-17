"""The MCP surface Copilot sees: tool names/schemas, and calls through the real MCP server object."""

import asyncio

from qa_harness.mcp_server import build_server
from qa_harness.models import Outcome

from .fakes import NODE, ScriptedExecutor, make_services

EXPECTED_TOOLS = {
    "qa_ready_tickets",
    "jira_get_ticket",
    "list_devices",
    "discover_scenarios",
    "run_on_sauce",
    "get_failure_evidence",
    "file_jira_bug",
    "publish_results_to_jira",
    "get_pr_description",
    "open_pull_request",
    "get_run_report",
}


def _text(result) -> str:
    return result.content[0].text


def test_tools_and_schemas(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{}]))
    tools = {t.name: t for t in asyncio.run(build_server(svc.settings, svc).list_tools())}
    assert set(tools) == EXPECTED_TOOLS
    bug_schema = tools["file_jira_bug"].input_schema
    assert set(bug_schema["required"]) == {
        "run_id",
        "scenario_id",
        "title",
        "severity",
        "steps_to_reproduce",
        "expected",
        "actual",
    }
    assert "scenario_ids" in tools["run_on_sauce"].input_schema["required"]


def test_run_evidence_report_through_mcp(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]))
    server = build_server(svc.settings, svc)

    async def flow():
        out = _text(await server.call_tool("run_on_sauce", {"ticket_key": "APP-1", "scenario_ids": [NODE]}))
        run_id = out.split()[1]
        evidence = _text(
            await server.call_tool("get_failure_evidence", {"run_id": run_id, "scenario_id": NODE, "device": "pixel"})
        )
        report = _text(await server.call_tool("get_run_report", {"ticket_key_or_run_id": "APP-1"}))
        error = _text(await server.call_tool("run_on_sauce", {"ticket_key": "APP-1", "scenario_ids": []}))
        return run_id, evidence, report, error

    run_id, evidence, report, error = asyncio.run(flow())
    assert run_id.startswith("APP-1-")
    assert "Locator inventory" in evidence
    assert f"run_id: {run_id}" in report and "**Status:** failed" in report
    assert error.startswith("Error: No scenario ids")
