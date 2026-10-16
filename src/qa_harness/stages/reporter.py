"""Stage helpers: render the run as markdown for the PR, the Jira comment, and the run directory."""

from __future__ import annotations

from collections import defaultdict

from ..models import FailureCategory, Outcome, TestResult
from ..state import RunState

ICON = {Outcome.passed: "✅", Outcome.failed: "❌", Outcome.error: "⚠️", Outcome.skipped: "⏭️"}
STATUS_TEXT = {
    "passed": "All generated tests pass on every device.",
    "product_bug": "Tests are valid and found product defect(s). Bugs were filed.",
    "needs_human": "Some failures need a human decision.",
    "failed": "Tests still fail after self-healing.",
    "error": "The run errored before completing.",
    "running": "In progress.",
}


def final_results(state: RunState) -> list[TestResult]:
    """Latest result per (test, device) across all attempts."""
    latest: dict[tuple[str, str], TestResult] = {}
    for run in state.runs:
        for r in run.results:
            latest[(r.node_id, r.device)] = r
    return sorted(latest.values(), key=lambda r: (r.node_id, r.device))


def latest_verdicts(state: RunState) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for report in state.triage:
        for v in report.verdicts:
            out[(v.node_id, v.device)] = v.category.value
    return out


def matrix_table(state: RunState) -> str:
    results = final_results(state)
    if not results:
        return "_No tests were executed._"
    devices = sorted({r.device for r in results})
    grid: dict[str, dict[str, TestResult]] = defaultdict(dict)
    for r in results:
        grid[r.node_id][r.device] = r
    lines = ["| Test | " + " | ".join(devices) + " |", "|---|" + "---|" * len(devices)]
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
        lines.append(f"| {_label(row)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _label(row: dict[str, TestResult]) -> str:
    r = next(iter(row.values()))
    file_line = r.node_id.rsplit("/", 1)[-1]
    return f"{r.name} <sub>`{file_line}`</sub>" if r.name else f"`{file_line}`"


def render_report(state: RunState, *, for_jira: bool = False) -> str:
    plan = state.plan
    results = final_results(state)
    counts = {o: sum(1 for r in results if r.outcome == o) for o in Outcome}
    out = [
        f"## QA automation report: {state.ticket_key}",
        f"**Status:** {state.status} — {STATUS_TEXT.get(state.status, '')}",
        f"**Results:** {counts[Outcome.passed]} passed, {counts[Outcome.failed]} failed, "
        f"{counts[Outcome.error]} errored, {counts[Outcome.skipped]} skipped across "
        f"{len({r.device for r in results})} device(s) in {len(state.runs)} attempt(s).",
    ]
    if state.pr_url and for_jira:
        out.append(f"**Pull request:** [{state.pr_url}]({state.pr_url})")
    if state.bug_keys:
        out.append(f"**Bugs filed:** {', '.join(state.bug_keys)}")
    out += ["", "### Device matrix", matrix_table(state)]

    if plan:
        out += ["", "### Test plan coverage"]
        for c in plan.test_cases:
            mark = "automated" if c.automatable else f"manual — {c.automation_notes}"
            out.append(f"- **{c.id}** [{c.kind.value}, P{c.priority}] {c.title} _({mark})_")
        if plan.ambiguities:
            out += ["", "### Assumptions and open questions"] + [f"- {a}" for a in plan.ambiguities]
        if plan.risks and not for_jira:
            out += ["", "### Risks considered"] + [f"- {r}" for r in plan.risks]

    verdicts = [v for report in state.triage for v in report.verdicts]
    unresolved = [
        v
        for v in verdicts
        if v.category in (FailureCategory.product_bug, FailureCategory.needs_human)
        and any(r.node_id == v.node_id and r.device == v.device and r.outcome != Outcome.passed for r in results)
    ]
    if unresolved:
        names = {r.node_id: r.name or r.node_id for r in results}
        out += ["", "### Open findings"]
        for v in unresolved:
            out.append(
                f"- **{v.category.value}** {names.get(v.node_id, v.node_id)} on {v.device} "
                f"({v.confidence:.0%}): {v.root_cause}"
            )
    healed = sum(1 for v in verdicts if v.category == FailureCategory.test_defect)
    if healed:
        out.append(f"\n_Self-healing fixed or attempted {healed} test-defect failure(s) before the final run._")

    if state.files_changed and not for_jira:
        out += ["", "### Files"] + [f"- `{f}`" for f in state.files_changed]
    if state.cost and not for_jira:
        out.append(
            f"\n<sub>LLM cost ${state.cost.get('spent_usd', 0):.2f} over {state.cost.get('calls', 0)} calls · "
            f"run `{state.run_id}`</sub>"
        )
    return "\n".join(out)
