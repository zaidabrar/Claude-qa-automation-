"""Stage: Jira ticket -> structured, traceable test plan."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..llm import LLM
from ..models import TestPlan, Ticket
from ..prompts import load_prompt


def render_ticket(ticket: Ticket) -> str:
    parts = [
        f"# {ticket.key}: {ticket.summary}",
        f"Type: {ticket.issue_type} | Priority: {ticket.priority} | Status: {ticket.status}",
    ]
    if ticket.components:
        parts.append(f"Components: {', '.join(ticket.components)}")
    if ticket.labels:
        parts.append(f"Labels: {', '.join(ticket.labels)}")
    parts.append(f"\n## Description\n{ticket.description or '(empty)'}")
    if ticket.acceptance_criteria:
        parts.append(f"\n## Acceptance criteria\n{ticket.acceptance_criteria}")
    if ticket.linked_issues:
        parts.append("\n## Linked issues\n" + "\n".join(f"- {x}" for x in ticket.linked_issues))
    if ticket.comments:
        parts.append("\n## Recent comments\n" + "\n".join(f"- {c[:800]}" for c in ticket.comments))
    return "\n".join(parts)


def existing_tests_index(tests_root: Path) -> str:
    tests = sorted((tests_root / "tests").glob("test_*.py")) if (tests_root / "tests").exists() else []
    pages = sorted((tests_root / "pages").glob("*.py")) if (tests_root / "pages").exists() else []
    lines = ["Existing page objects: " + (", ".join(p.stem for p in pages if p.stem != "__init__") or "none")]
    lines.append("Existing test modules: " + (", ".join(t.stem for t in tests) or "none"))
    return "\n".join(lines)


def build_plan(llm: LLM, ticket: Ticket, settings: Settings) -> TestPlan:
    platforms = sorted({d.platform.lower() for d in settings.sauce.devices}) or ["android", "ios"]
    devices = "\n".join(
        f"- {d.name}: {d.platform} {d.platform_version} ({d.device_name}, {'real' if d.real_device else 'emulator'})"
        for d in settings.sauce.devices
    )
    content = (
        f"{render_ticket(ticket)}\n\n"
        f"## Test environment\nPlatforms in scope: {', '.join(platforms)}\n"
        f"Device matrix:\n{devices or '- (not configured)'}\n\n"
        f"## Existing automation\n{existing_tests_index(settings.tests_root)}\n\n"
        f"Produce the test plan for {ticket.key}."
    )
    plan = llm.structured(system=load_prompt("planner"), content=content, output=TestPlan)
    plan.ticket_key = ticket.key
    return plan
