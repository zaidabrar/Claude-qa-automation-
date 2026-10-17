"""Markdown reports for the PR description, the Jira comment, and the agent.

Status is always computed from recorded results, never from what the agent says happened.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Outcome, TestResult
from .state import QaRun

ICON = {Outcome.passed: "✅", Outcome.failed: "❌", Outcome.error: "⚠️", Outcome.skipped: "⏭️"}
STATUS_TEXT = {
    "passed": "All scenarios pass on every device.",
    "failed": "Some scenarios fail.",
    "skipped": "Every scenario was skipped on the selected devices.",
    "not_run": "Nothing has been run yet.",
}


def _label(r: TestResult) -> str:
    file_line = r.node_id.rsplit("/", 1)[-1]
    return f"{r.name} <sub>`{file_line}`</sub>" if r.name else f"`{file_line}`"


def matrix_table(run: QaRun) -> str:
    results = run.final_results()
    if not results:
        return "_No scenarios were executed._"
    devices = sorted({r.device for r in results})
    grid: dict[str, dict[str, TestResult]] = defaultdict(dict)
    for r in results:
        grid[r.node_id][r.device] = r
    lines = ["| Scenario | " + " | ".join(devices) + " |", "|---|" + "---|" * len(devices)]
    for row in grid.values():
        cells = []
        for d in devices:
            r = row.get(d)
            if r is None:
                cells.append("–")
            elif r.sauce_url:
                cells.append(f"[{ICON[r.outcome]}]({r.sauce_url})")
            else:
                cells.append(ICON[r.outcome])
        lines.append(f"| {_label(next(iter(row.values())))} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_report(run: QaRun, *, jira_url: str = "", for_jira: bool = False) -> str:
    results = run.final_results()
    counts = {o: sum(1 for r in results if r.outcome == o) for o in Outcome}
    status = run.status()
    out = [
        f"## QA automation report: {run.ticket_key}",
        f"**Status:** {status} — {STATUS_TEXT[status]}",
        f"**Results:** {counts[Outcome.passed]} passed, {counts[Outcome.failed]} failed, "
        f"{counts[Outcome.error]} errored, {counts[Outcome.skipped]} skipped on "
        f"{len({r.device for r in results})} Sauce Labs device(s) after {len(run.attempts)} attempt(s).",
    ]
    if run.bugs:
        out.append("**Bugs filed:** " + ", ".join(sorted(set(run.bugs.values()))))
    if for_jira and run.pr_url:
        out.append(f"**Pull request:** [{run.pr_url}]({run.pr_url})")
    if jira_url and not for_jira:
        out.append(f"**Jira:** [{run.ticket_key}]({jira_url})")
    out += ["", "### Scenario × device", matrix_table(run)]

    failing = [r for r in results if r.outcome in (Outcome.failed, Outcome.error)]
    if failing:
        out += ["", "### Failing"]
        for r in failing:
            bug = run.bugs.get(r.node_id)
            first_line = (r.message.splitlines() or ["(no message)"])[0][:200]
            out.append(f"- {r.name or r.node_id} on {r.device}: {first_line}" + (f" → {bug}" if bug else ""))
    out.append(f"\n<sub>qa-harness run `{run.run_id}` · results recorded from Sauce Labs, not self-reported</sub>")
    return "\n".join(out)
