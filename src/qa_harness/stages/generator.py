"""Stage: test plan -> Appium page objects and pytest tests, written by a tool-using agent."""

from __future__ import annotations

import re

from ..config import Settings
from ..llm import LLM
from ..models import GeneratedFile, GenerationResult, TestPlan
from ..prompts import load_prompt
from ..tools import Workspace, build_workspace_tools, run_pytest_collect


def ticket_slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def generate_tests(llm: LLM, plan: TestPlan, settings: Settings, ws: Workspace) -> GenerationResult:
    tests_dir = settings.project.tests_dir
    system = load_prompt(
        "generator", tests_dir=tests_dir, ticket_key=plan.ticket_key, ticket_slug=ticket_slug(plan.ticket_key)
    )
    automatable = [c for c in plan.test_cases if c.automatable]
    task = (
        f"Automate the following test plan.\n\n```json\n{plan.model_dump_json(indent=2)}\n```\n\n"
        f"{len(automatable)} of {len(plan.test_cases)} cases are automatable. "
        "Start by exploring the existing suite."
    )
    outcome = llm.run_agent(
        system=system,
        task=task,
        tools=build_workspace_tools(ws),
        result_model=GenerationResult,
    )
    result: GenerationResult = outcome.result  # type: ignore[assignment]
    # Trust the filesystem over the model's account of what it wrote.
    reported = {f.path for f in result.files}
    result.files += [GeneratedFile(path=p, purpose="(written, not reported)") for p in sorted(ws.written - reported)]
    return result


def verify_collection(settings: Settings, node_ids: list[str]) -> tuple[list[str], str]:
    """Return the node ids pytest actually collects, plus raw output for diagnostics."""
    out = run_pytest_collect(settings.repo_root, settings.tests_root, node_ids)
    collected = [line.strip() for line in out.splitlines() if "::" in line and not line.startswith("exit=")]
    return collected, out
