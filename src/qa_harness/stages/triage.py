"""Stage: classify failures (test defect / product bug / environment), heal tests, draft bugs."""

from __future__ import annotations

import base64
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import LLM
from ..models import BugReport, FailureVerdict, GenerationResult, TestPlan, TestResult, Ticket, TriageReport
from ..prompts import load_prompt
from ..state import FlakeMemory
from ..tools import Workspace, build_workspace_tools

MAX_PAGE_SOURCE = 60_000
MAX_IMAGE_BYTES = 3_500_000
CRASH_PATTERNS = re.compile(r"FATAL EXCEPTION|ANR in|has crashed|SIGABRT|SIGSEGV|Terminating app|EXC_BAD_ACCESS", re.I)


def _read(path: str | None, limit: int) -> str:
    if not path or not Path(path).is_file():
        return ""
    text = Path(path).read_text(errors="replace")
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _log_excerpt(path: str | None) -> str:
    """Crash lines with context plus the log tail: the parts that matter for triage."""
    if not path or not Path(path).is_file():
        return ""
    lines = Path(path).read_text(errors="replace").splitlines()
    picked: list[str] = []
    for i, line in enumerate(lines):
        if CRASH_PATTERNS.search(line):
            picked += lines[max(0, i - 3) : i + 25] + ["..."]
            if len(picked) > 200:
                break
    return "\n".join(picked[:200] + ["--- tail ---"] + lines[-80:])


def _test_source(settings: Settings, node_id: str) -> str:
    return _read(str(settings.repo_root / node_id.split("::")[0]), 20_000)


def _failure_blocks(settings: Settings, failures: list[TestResult], memory: FlakeMemory) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for r in failures:
        rate = memory.flake_rate(r.node_id, r.device)
        text = [
            f"## Failure: {r.node_id} on {r.device}",
            f"Outcome: {r.outcome.value} after {r.duration_s}s | Sauce: {r.sauce_url or 'n/a'}",
            f"Historical flip rate: {rate:.0%}" if rate is not None else "Historical flip rate: unknown",
            f"### Error\n{r.message}",
            f"### Traceback\n```\n{r.traceback[-4000:]}\n```",
        ]
        if src := _read(r.artifacts.get("page_source"), MAX_PAGE_SOURCE):
            text.append(f"### Page source at failure ({r.artifacts['page_source']})\n```xml\n{src}\n```")
        for name in ("device_log", "logcat", "appium_log"):
            if excerpt := _log_excerpt(r.artifacts.get(name)):
                text.append(f"### {name} excerpt\n```\n{excerpt[-12000:]}\n```")
        blocks.append({"type": "text", "text": "\n\n".join(text)})
        shot = r.artifacts.get("screenshot")
        if shot and Path(shot).is_file() and Path(shot).stat().st_size <= MAX_IMAGE_BYTES:
            blocks.append({"type": "text", "text": f"Screenshot at failure ({r.node_id} on {r.device}):"})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(Path(shot).read_bytes()).decode(),
                    },
                }
            )
    return blocks


def triage_failures(
    llm: LLM,
    settings: Settings,
    ticket: Ticket,
    plan: TestPlan,
    failures: list[TestResult],
    memory: FlakeMemory,
) -> TriageReport:
    """One call per failing test (all of its devices together), so cross-device patterns are visible."""
    by_test: dict[str, list[TestResult]] = defaultdict(list)
    for r in failures:
        by_test[r.node_id].append(r)

    verdicts: list[FailureVerdict] = []
    summaries: list[str] = []
    for node_id, results in by_test.items():
        header = (
            f"Ticket {ticket.key}: {ticket.summary}\n\nAcceptance criteria:\n{ticket.acceptance_criteria or '(none)'}"
            f"\n\nTest plan cases:\n{_plan_digest(plan)}\n\n## Test source ({node_id.split('::')[0]})\n"
            f"```python\n{_test_source(settings, node_id)}\n```\n\n"
            f"Devices that ran this test: {', '.join(sorted({r.device for r in results}))}"
        )
        content = [{"type": "text", "text": header}, *_failure_blocks(settings, results, memory)]
        content.append({"type": "text", "text": "Return one verdict per (test, device) failure above."})
        report = llm.structured(
            system=load_prompt("triage"), content=content, output=TriageReport, effort=settings.llm.triage_effort
        )
        verdicts += report.verdicts
        summaries.append(report.summary)
    return TriageReport(verdicts=verdicts, summary="\n".join(summaries))


def _plan_digest(plan: TestPlan) -> str:
    return "\n".join(f"- {c.id} [{c.kind.value}] {c.title} (traces: {'; '.join(c.traces_to)})" for c in plan.test_cases)


def heal_tests(
    llm: LLM,
    settings: Settings,
    ws: Workspace,
    verdicts: list[FailureVerdict],
    failures: list[TestResult],
) -> GenerationResult:
    by_key = {(r.node_id, r.device): r for r in failures}
    sections = []
    for v in verdicts:
        r = by_key.get((v.node_id, v.device))
        if r is None:
            continue
        page_source = r.artifacts.get("page_source")
        rel = None
        if page_source:
            try:  # the agent's read_file tool takes repo-relative paths
                rel = Path(page_source).resolve().relative_to(settings.repo_root)
            except ValueError:
                rel = f"{page_source} (outside the repo; not readable by tools)"
        sections.append(
            f"### {v.node_id} on {v.device}\n"
            f"Root cause (triage): {v.root_cause}\nSuggested fix: {v.suggested_fix}\n"
            f"Error: {r.message}\nTraceback:\n```\n{r.traceback[-3000:]}\n```\n"
            f"Page source file: {rel or 'not captured'}"
        )
    task = "Fix these test defects.\n\n" + "\n\n".join(sections)
    outcome = llm.run_agent(
        system=load_prompt("healer"),
        task=task,
        tools=build_workspace_tools(ws),
        result_model=GenerationResult,
        max_turns=max(20, settings.llm.max_agent_turns // 2),
    )
    return outcome.result  # type: ignore[return-value]


def draft_bug(llm: LLM, ticket: Ticket, verdicts: list[FailureVerdict], results: list[TestResult]) -> BugReport:
    devices = ", ".join(sorted({v.device for v in verdicts}))
    evidence = "\n\n".join(
        f"Device {v.device}: {v.root_cause}\nEvidence:\n" + "\n".join(f"- {e}" for e in v.evidence) for v in verdicts
    )
    sauce = "\n".join(f"- {r.device}: {r.sauce_url}" for r in results if r.sauce_url)
    content = (
        f"Source ticket {ticket.key}: {ticket.summary}\nAcceptance criteria:\n{ticket.acceptance_criteria}\n\n"
        f"Failing automated test: {verdicts[0].node_id}\nAffected devices: {devices}\n\n"
        f"Triage findings:\n{evidence}\n\nSauce Labs sessions (video + logs):\n{sauce or 'n/a'}"
    )
    return llm.structured(system=load_prompt("bug"), content=content, output=BugReport)
