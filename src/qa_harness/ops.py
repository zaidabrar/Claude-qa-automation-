"""The harness operations behind every MCP tool and CLI command. No LLM here: Copilot decides,
these functions act, record, and enforce the rules that must not depend on the agent's judgement.

Guardrails enforced in code:
* a bug can only be filed for a scenario that is failing in the recorded Sauce Labs results,
  and only once per scenario per run;
* pass/fail in Jira and the PR comes from recorded results, never from the agent;
* only files inside the test project are committed;
* in dry_run mode every Jira/GitHub write is logged and skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from .evidence import hint, locator_inventory, log_excerpt
from .integrations import notify
from .models import BugReport, Outcome, Ticket
from .report import render_report
from .services import Services
from .state import FlakeMemory, Guard, QaRun, RunStore

FAILED = (Outcome.failed, Outcome.error)


def _memory(svc: Services) -> FlakeMemory:
    return FlakeMemory(svc.settings.runs_root / "flake_memory.json")


def _store(svc: Services, run_id: str) -> tuple[RunStore, QaRun]:
    store = RunStore(svc.settings.runs_root, run_id)
    return store, store.load()


def _rel(svc: Services, path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(svc.settings.repo_root))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------- Jira (read)


def render_ticket(ticket: Ticket) -> str:
    parts = [
        f"# {ticket.key}: {ticket.summary}",
        f"Type: {ticket.issue_type} | Priority: {ticket.priority} | Status: {ticket.status}",
    ]
    if ticket.components:
        parts.append(f"Components: {', '.join(ticket.components)}")
    if ticket.labels:
        parts.append(f"Labels: {', '.join(ticket.labels)}")
    if ticket.url:
        parts.append(f"URL: {ticket.url}")
    parts.append(f"\n## Description\n{ticket.description or '(empty)'}")
    if ticket.acceptance_criteria:
        parts.append(f"\n## Acceptance criteria\n{ticket.acceptance_criteria}")
    if ticket.linked_issues:
        parts.append("\n## Linked issues\n" + "\n".join(f"- {x}" for x in ticket.linked_issues))
    if ticket.comments:
        parts.append("\n## Recent comments\n" + "\n".join(f"- {c[:800]}" for c in ticket.comments))
    return "\n".join(parts)


def get_ticket(svc: Services, key: str) -> str:
    return render_ticket(svc.require_jira().get_ticket(key))


def ready_tickets(svc: Services, limit: int = 20) -> str:
    jira = svc.require_jira()
    jql = exclude_done(svc.settings.jira.ready_jql, svc.settings.jira.done_label)
    keys = jira.search_keys(jql, limit=limit)
    if not keys:
        return f"No tickets match: {jql}"
    return "\n".join(f"- {k}: {jira.get_ticket(k).summary}" for k in keys)


def exclude_done(jql: str, label: str) -> str:
    parts = re.split(r"\s+ORDER\s+BY\s+", jql, maxsplit=1, flags=re.I)
    where = f'({parts[0]}) AND (labels IS EMPTY OR labels != "{label}")'
    return where + (f" ORDER BY {parts[1]}" if len(parts) > 1 else "")


# ---------------------------------------------------------------------- test project


def list_devices(svc: Services) -> str:
    devices = svc.settings.sauce.devices
    if not devices:
        return "No devices configured (sauce.devices in qa_harness.yaml)."
    return "\n".join(
        f"- {d.name}: {d.platform} {d.platform_version} {d.device_name!r} ({'real' if d.real_device else 'vm'})"
        for d in devices
    )


def discover(svc: Services, feature_files: list[str] | None = None) -> str:
    features = [svc.framework.to_project_path(f) or f for f in (feature_files or [])]
    return svc.framework.discover(features or None).summary()


# ---------------------------------------------------------------------- Sauce Labs


def run_scenarios(
    svc: Services,
    ticket_key: str,
    scenario_ids: list[str],
    devices: list[str] | None = None,
    run_id: str | None = None,
) -> tuple[QaRun, str]:
    """Run scenarios on Sauce Labs. Pass ``run_id`` to add an attempt (e.g. after a fix) to an existing run."""
    if not scenario_ids:
        raise ValueError("No scenario ids given; get them from discover_scenarios")
    configured = {d.name for d in svc.settings.sauce.devices}
    names = devices or sorted(configured)
    unknown = set(names) - configured
    if unknown:
        raise ValueError(
            f"Unknown device(s): {', '.join(sorted(unknown))}. Configured: {', '.join(sorted(configured))}"
        )

    if run_id:
        store, run = _store(svc, run_id)
        if run.ticket_key != ticket_key:
            raise ValueError(f"Run {run_id} belongs to {run.ticket_key}, not {ticket_key}")
    else:
        store, run = RunStore.new(svc.settings.runs_root, ticket_key)

    attempt = len(run.attempts) + 1
    summary = svc.executor(store.dir).run(
        {d: list(scenario_ids) for d in names}, attempt, f"{svc.settings.sauce.build_prefix}-{run.run_id}"
    )
    run.attempts.append(summary)
    run.scenario_ids = sorted(set(run.scenario_ids) | set(scenario_ids))
    run.devices = sorted(set(run.devices) | set(names))
    store.save(run)
    memory = _memory(svc)
    memory.record(summary)
    store.event("attempt", {"attempt": attempt, "devices": names, **summary.counts()})

    lines = [f"run_id: {run.run_id} (attempt {attempt}) {summary.counts()}"]
    for r in summary.results:
        lines.append(f"- {r.outcome.value.upper():7} {r.name or r.node_id} on {r.device} {r.sauce_url or ''}".rstrip())
        if r.outcome in FAILED:
            same = [x for x in summary.results if x.node_id == r.node_id]
            lines.append(f"    {(r.message.splitlines() or [''])[0][:300]}")
            lines.append(f"    hint: {hint(r, same, memory.history(r.node_id, r.device)[:-1])}")
    if summary.failures:
        lines.append("\nFor each failure call get_failure_evidence(run_id, scenario_id, device) before deciding.")
    return run, "\n".join(lines)


def failure_evidence(svc: Services, run_id: str, scenario_id: str, device: str) -> str:
    _, run = _store(svc, run_id)
    results = {(r.node_id, r.device): r for r in run.final_results()}
    r = results.get((scenario_id, device))
    if r is None:
        raise ValueError(f"No result for {scenario_id} on {device} in {run_id}")
    memory = _memory(svc)
    history = memory.history(scenario_id, device)
    same = [x for x in run.final_results() if x.node_id == scenario_id]
    out = [
        f"# {r.name or scenario_id} on {device}: {r.outcome.value}",
        f"Sauce Labs session (video, logs): {r.sauce_url or 'n/a'}",
        f"Hint: {hint(r, same, history[:-1])}",
        f"Other devices: {', '.join(f'{x.device}={x.outcome.value}' for x in same if x.device != device) or 'none'}",
        f"History on this device (oldest→newest): {' '.join(history[-10:]) or 'none'}",
        f"\n## Failure\n```\n{r.message[:2000]}\n```",
        f"\n## Stack trace (top)\n```\n{chr(10).join(r.traceback.splitlines()[:40])}\n```",
    ]
    if r.artifacts.get("screenshot"):
        out.append(f"\n## Screenshot\n{_rel(svc, r.artifacts['screenshot'])} (open it to see the screen)")
    if source := r.artifacts.get("page_source"):
        text = Path(source).read_text(errors="replace") if Path(source).is_file() else ""
        out.append(
            f"\n## Locator inventory at failure (from {_rel(svc, source)})\n"
            "Use only attributes listed here when fixing locators.\n"
            f"```\n{locator_inventory(text)}\n```"
        )
    for name in ("device_log", "logcat", "appium_log"):
        if excerpt := log_excerpt(r.artifacts.get(name)):
            out.append(f"\n## {name} excerpt\n```\n{excerpt[-8000:]}\n```")
    return "\n".join(out)


# ---------------------------------------------------------------------- Jira (write)


def file_bug(svc: Services, run_id: str, scenario_id: str, bug: BugReport) -> str:
    store, run = _store(svc, run_id)
    if not svc.settings.autonomy.file_bugs:
        return "Bug filing is disabled (autonomy.file_bugs: false). Report the defect in the PR instead."
    if scenario_id in run.bugs:
        return f"Already filed as {run.bugs[scenario_id]} for this run."
    failing = [r for r in run.final_results() if r.node_id == scenario_id and r.outcome in FAILED]
    if not failing:
        raise ValueError(
            f"{scenario_id} is not failing in run {run_id}. Bugs can only be filed from a recorded failure."
        )
    jira = svc.require_jira()
    project = svc.settings.jira.bug_project or run.ticket_key.split("-")[0]
    body = _bug_markdown(bug, run.ticket_key, scenario_id, failing)
    key = Guard(svc.settings.autonomy.mode, store).run(
        f"create bug in {project}",
        bug.title,
        lambda: jira.create_bug(project, bug.title, body, svc.settings.jira.bug_labels, _priority(bug.severity)),
    )
    if not key:
        return f"[dry-run] Would file in {project}:\n\n# {bug.title}\n{body}"
    run.bugs[scenario_id] = key
    store.save(run)
    for r in failing:
        shot = r.artifacts.get("screenshot")
        if shot and Path(shot).is_file():
            try:
                jira.attach(key, Path(shot))
            except RuntimeError as exc:
                store.event("attach_failed", {"bug": key, "error": str(exc)})
    try:
        jira.link(run.ticket_key, key)
    except RuntimeError as exc:
        store.event("link_failed", {"bug": key, "error": str(exc)})
    return f"Filed {key}: {svc.settings.jira.base_url.rstrip('/')}/browse/{key}"


def publish_to_jira(svc: Services, run_id: str) -> str:
    """Comment the report on the ticket, transition it by the recorded status, and label it done."""
    store, run = _store(svc, run_id)
    jira = svc.require_jira()
    guard = Guard(svc.settings.autonomy.mode, store)
    key, status = run.ticket_key, run.status()
    if status == "not_run":
        raise ValueError("Nothing has been run in this run yet")
    guard.run(f"comment on {key}", "QA report", lambda: jira.comment(key, render_report(run, for_jira=True)))
    done = [f"commented on {key}"]
    t = svc.settings.jira.transitions
    target = t.on_pass if status == "passed" else t.on_fail if status == "failed" else None
    if target and svc.settings.autonomy.transition_jira:
        moved = guard.run(f"transition {key}", target, lambda: jira.transition(key, target))
        done.append(f"transitioned to {target}" if moved else f"transition {target!r} not available")
    guard.run(f"label {key}", svc.settings.jira.done_label, lambda: jira.add_label(key, svc.settings.jira.done_label))
    dry = svc.settings.autonomy.mode.value == "dry_run"
    run.jira_reported = not dry
    store.save(run)
    if not dry:
        emoji = ":white_check_mark:" if status == "passed" else ":x:"
        bugs = f" · bugs {', '.join(sorted(set(run.bugs.values())))}" if run.bugs else ""
        notify.slack(svc.secrets.slack_webhook, f"{emoji} QA {key}: *{status}*{bugs}")
    prefix = "[dry-run] would have " if dry else ""
    return f"{prefix}{', '.join(done)} (status: {status})"


# ---------------------------------------------------------------------- GitHub


def pr_description(svc: Services, run_id: str) -> str:
    _, run = _store(svc, run_id)
    jira_url = f"{svc.settings.jira.base_url.rstrip('/')}/browse/{run.ticket_key}" if svc.settings.jira.base_url else ""
    return render_report(run, jira_url=jira_url)


def open_pull_request(svc: Services, run_id: str, title: str | None = None) -> str:
    """Commit the test project's changes on a QA branch, push, and open (or update) a draft PR."""
    store, run = _store(svc, run_id)
    git = svc.git
    if git is None:
        raise RuntimeError("Not a git repository")
    tests_dir = svc.settings.project.tests_dir
    changed = git.changed_files(tests_dir)
    branch = git.current_branch()
    if branch == svc.settings.project.base_branch:
        branch = f"{svc.settings.project.branch_prefix}{run.ticket_key.lower()}"
        git.create_branch(branch)
    if changed:
        git.commit(
            changed, f"test({run.ticket_key}): automated mobile scenarios\n\nValidated on Sauce Labs (run {run_id})."
        )
    title = title or f"test({run.ticket_key}): automated mobile scenarios"
    if run.status() != "passed":
        title = f"[{run.status()}] {title}"
    body = pr_description(svc, run_id)
    guard = Guard(svc.settings.autonomy.mode, store)
    if guard.run("push branch", branch, lambda: git.push(branch) or True) is None:
        return f"[dry-run] Committed {len(changed)} file(s) on {branch}; not pushed.\n\nPR description:\n{body}"
    if svc.github is None:
        repo = svc.settings.github.repo or git.remote_repo() or "<owner>/<repo>"
        return (
            f"Pushed {branch}. No GITHUB_TOKEN, so open the PR yourself (or with the GitHub MCP server):\n"
            f"https://github.com/{repo}/compare/{svc.settings.project.base_branch}...{branch}?expand=1\n\n"
            f"Title: {title}\n\n{body}"
        )
    pr = guard.run(
        "open pull request",
        title,
        lambda: svc.github.open_or_update_pr(branch, svc.settings.project.base_branch, title, body),
    )
    run.pr_url = pr.get("html_url") if pr else None
    store.save(run)
    return f"Pull request: {run.pr_url}"


# ---------------------------------------------------------------------- helpers


def _priority(severity: str) -> str | None:
    return {"blocker": "Highest", "critical": "High", "major": "Medium", "minor": "Low", "trivial": "Lowest"}.get(
        severity.lower()
    )


def _bug_markdown(bug: BugReport, ticket_key: str, scenario_id: str, results) -> str:
    return "\n".join(
        [
            f"Found by automated QA while verifying {ticket_key}. Severity: {bug.severity}.",
            "",
            "## Environment",
            *[f"- {r.device} (Sauce Labs real device)" for r in results],
            "",
            "## Steps to reproduce",
            *[f"- {i}. {s}" for i, s in enumerate(bug.steps_to_reproduce, 1)],
            "",
            "## Expected",
            bug.expected,
            "",
            "## Actual",
            bug.actual,
            "",
            "## Violated acceptance criteria",
            *([f"- {c}" for c in bug.violated_criteria] or ["- (not specified)"]),
            "",
            "## Evidence",
            *([f"- {e}" for e in bug.evidence] or ["- See the Sauce Labs sessions"]),
            *[f"- Failure on {r.device}: `{(r.message.splitlines() or [''])[0][:300]}`" for r in results],
            "",
            "## Sauce Labs sessions (video + logs)",
            *[f"- {r.device}: [{r.sauce_url}]({r.sauce_url})" for r in results if r.sauce_url],
            "",
            f"Automated scenario: `{scenario_id}`",
        ]
    )
