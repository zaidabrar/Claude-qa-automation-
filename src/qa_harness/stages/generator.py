"""Stage: test plan -> Cucumber features, step definitions, and page objects, written by a tool-using agent."""

from __future__ import annotations

import re

from ..config import Settings
from ..framework import TestFramework
from ..llm import LLM
from ..models import GeneratedFile, GenerationResult, TestPlan
from ..prompts import load_prompt
from ..tools import Workspace, build_workspace_tools


def ticket_slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def generate_tests(
    llm: LLM, plan: TestPlan, settings: Settings, ws: Workspace, framework: TestFramework
) -> GenerationResult:
    system = load_prompt(
        "generator",
        tests_dir=settings.project.tests_dir,
        ticket_key=plan.ticket_key,
        ticket_slug=ticket_slug(plan.ticket_key),
    )
    automatable = [c for c in plan.test_cases if c.automatable]
    task = (
        f"Automate the following test plan.\n\n```json\n{plan.model_dump_json(indent=2)}\n```\n\n"
        f"{len(automatable)} of {len(plan.test_cases)} cases are automatable. "
        "Start by reading the team conventions and exploring the existing suite."
    )
    outcome = llm.run_agent(
        system=system,
        task=task,
        tools=build_workspace_tools(ws, framework),
        result_model=GenerationResult,
    )
    result: GenerationResult = outcome.result  # type: ignore[assignment]
    # Trust the filesystem over the model's account of what it wrote.
    reported = {f.path for f in result.files}
    result.files += [GeneratedFile(path=p, purpose="(written, not reported)") for p in sorted(ws.written - reported)]
    return result
