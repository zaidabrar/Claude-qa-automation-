"""End-to-end orchestration: Jira -> plan -> tests -> Sauce Labs -> triage/heal loop -> bugs -> PR -> Jira.

Each stage is checkpointed to ``<runs_dir>/<run_id>/state.json`` so a crashed or
budget-stopped run resumes where it left off (``qa-harness resume <run_id>``).
"""

from __future__ import annotations

import logging
import re
import traceback
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .config import DeviceConfig, Secrets, Settings
from .framework import TestFramework
from .integrations import notify
from .integrations.github import Git, GitHubClient
from .integrations.jira import JiraClient
from .llm import LLM
from .models import FailureCategory, Outcome, RunSummary, Ticket
from .stages.generator import generate_tests, ticket_slug
from .stages.planner import build_plan
from .stages.reporter import final_results, latest_verdicts, render_report
from .stages.triage import draft_bug, heal_tests, triage_failures
from .state import STAGES, FlakeMemory, Guard, RunState, RunStore
from .tools import Workspace

log = logging.getLogger(__name__)


class Executor(Protocol):
    def devices(self) -> list[DeviceConfig]: ...
    def run(self, targets: dict[str, list[str]], attempt: int, build: str) -> RunSummary: ...


@dataclass
class Deps:
    settings: Settings
    secrets: Secrets
    llm: LLM
    framework: TestFramework
    executor: Executor
    load_ticket: Callable[[str], Ticket]
    jira: JiraClient | None = None
    git: Git | None = None
    github: GitHubClient | None = None


class Pipeline:
    def __init__(self, deps: Deps, store: RunStore, state: RunState, guard: Guard | None = None):
        self.d = deps
        self.s = deps.settings
        self.store = store
        self.state = state
        self.guard = guard or Guard(self.s.autonomy.mode, store)
        self.memory = FlakeMemory(self.s.runs_root / "flake_memory.json")
        self.ws = Workspace(self.s.repo_root, self.s.tests_root)
        deps.llm.on_event = lambda kind, data: store.event(kind, data)

    # ------------------------------------------------------------------ driver

    def run(self) -> RunState:
        st = self.state
        try:
            for stage in STAGES:
                if stage in st.completed_stages:
                    continue
                self.store.event("stage_start", {"stage": stage})
                log.info("[%s] %s", st.ticket_key, stage)
                getattr(self, f"_stage_{stage}")()
                st.completed_stages.append(stage)
                self._checkpoint()
                self.store.event("stage_done", {"stage": stage})
        except Exception as exc:
            st.status = "error"
            st.error = f"{type(exc).__name__}: {exc}"
            self.store.event("error", {"error": st.error, "traceback": traceback.format_exc()})
            self._checkpoint()
            notify.slack(self.d.secrets.slack_webhook, f":warning: QA agent errored on {st.ticket_key}: {st.error}")
            raise
        return st

    def _checkpoint(self) -> None:
        self.state.cost = self.d.llm.cost.as_dict()
        self.store.save(self.state)

    # ------------------------------------------------------------------ stages

    def _stage_ingest(self) -> None:
        self.state.ticket = self.d.load_ticket(self.state.ticket_key)
        t = self.s.jira.transitions.on_start
        if t and self.d.jira and self.s.autonomy.transition_jira:
            self.guard.run(
                f"transition {self.state.ticket_key}", t, lambda: self.d.jira.transition(self.state.ticket_key, t)
            )

    def _stage_plan(self) -> None:
        assert self.state.ticket
        self.state.plan = build_plan(self.d.llm, self.state.ticket, self.s)
        (self.store.dir / "plan.json").write_text(self.state.plan.model_dump_json(indent=2))
        if not any(c.automatable for c in self.state.plan.test_cases):
            raise RuntimeError("Test plan has no automatable cases; nothing to generate")

    def _stage_generate(self) -> None:
        assert self.state.plan and self.state.ticket
        self._prepare_branch()
        gen = generate_tests(self.d.llm, self.state.plan, self.s, self.ws, self.d.framework)
        self.state.generation = gen
        self.state.files_changed = sorted({f.path for f in gen.files} | self.ws.written)
        if not self._node_ids():
            raise RuntimeError("Generated scenarios could not be discovered (compile/Cucumber error); see audit.jsonl")

    def _stage_execute(self) -> None:
        st, auto = self.state, self.s.autonomy
        node_ids = self._node_ids()
        devices = [d.name for d in self.d.executor.devices()]
        if not devices:
            raise RuntimeError("No devices configured under sauce.devices")
        targets = {d: list(node_ids) for d in devices}
        heals = env_retries = 0
        build = f"{self.s.sauce.build_prefix}-{st.run_id}"

        while targets:
            attempt = len(st.runs) + 1
            summary = self.d.executor.run(targets, attempt, build)
            st.runs.append(summary)
            self.memory.record(summary)
            self._checkpoint()
            failures = summary.failures
            self.store.event("execution", {"attempt": attempt, **summary.counts()})
            if not failures:
                break

            report = triage_failures(self.d.llm, self.s, self.d.framework, st.ticket, st.plan, failures, self.memory)
            st.triage.append(report)
            self._checkpoint()
            verdict = {(v.node_id, v.device): v for v in report.verdicts}

            def category(r, verdict=verdict):
                v = verdict.get((r.node_id, r.device))
                return v.category if v else FailureCategory.needs_human

            env = [r for r in failures if category(r) == FailureCategory.environment]
            defects = [r for r in failures if category(r) == FailureCategory.test_defect]
            targets = defaultdict(list)

            if env and env_retries < auto.max_env_retries:
                env_retries += 1
                for r in env:
                    targets[r.device].append(r.node_id)

            if defects and heals < auto.max_heal_attempts:
                heals += 1
                defect_verdicts = [verdict[(r.node_id, r.device)] for r in defects]
                healed = heal_tests(self.d.llm, self.s, self.d.framework, self.ws, defect_verdicts, defects)
                self.state.files_changed = sorted(
                    set(st.files_changed) | {f.path for f in healed.files} | self.ws.written
                )
                # If healing broke collection, re-run the old ids so they surface as errors.
                node_ids = self._node_ids() or node_ids
                # Page objects are shared, so re-verify the whole ticket suite on affected devices.
                for device in {r.device for r in defects}:
                    targets[device] = list(node_ids)

            targets = {d: sorted(set(ids)) for d, ids in targets.items()}

        st.status = self._final_status()

    def _stage_publish(self) -> None:
        if self.state.status in ("running", "error"):  # resumed after execute completed
            self.state.status = self._final_status()
        self._file_bugs()
        self._open_pr()

    def _stage_report(self) -> None:
        st, s = self.state, self.s
        self._checkpoint()
        report_md = render_report(st)
        (self.store.dir / "report.md").write_text(report_md)
        key = st.ticket_key
        if self.d.jira:
            jira_md = render_report(st, for_jira=True)
            self.guard.run(f"comment on {key}", "QA report", lambda: self.d.jira.comment(key, jira_md))
            target = s.jira.transitions.on_pass if st.status == "passed" else s.jira.transitions.on_fail
            if target and s.autonomy.transition_jira and st.status in ("passed", "product_bug", "failed"):
                self.guard.run(f"transition {key}", target, lambda: self.d.jira.transition(key, target))
            self.guard.run(f"label {key}", s.jira.done_label, lambda: self.d.jira.add_label(key, s.jira.done_label))
        emoji = {"passed": ":white_check_mark:", "product_bug": ":beetle:"}.get(st.status, ":warning:")
        notify.slack(
            self.d.secrets.slack_webhook,
            f"{emoji} QA agent finished {key}: *{st.status}*"
            + (f" · PR {st.pr_url}" if st.pr_url else "")
            + (f" · bugs {', '.join(st.bug_keys)}" if st.bug_keys else ""),
        )

    # ------------------------------------------------------------------ helpers

    def _feature_files(self) -> list[str]:
        """Feature files this run created or changed, relative to the Maven project."""
        out = []
        for f in self.state.files_changed:
            if f.endswith(".feature"):
                rel = self.d.framework.to_project_path(f)
                if rel:
                    out.append(rel)
        return out

    def _node_ids(self) -> list[str]:
        features = self._feature_files()
        if not features:
            return []
        found = self.d.framework.discover(features)
        self.store.event(
            "discover",
            {"features": features, "scenarios": len(found.ids), "problems": found.problems, "compiled": found.compiled},
        )
        return found.ids

    def _prepare_branch(self) -> None:
        git, st = self.d.git, self.state
        if git is None:
            return
        resuming = st.branch is not None and git.current_branch() == st.branch
        if resuming:
            return
        if git.is_dirty([self.s.project.tests_dir]):
            raise RuntimeError(
                f"{self.s.project.tests_dir}/ has uncommitted changes; commit or stash them before running"
            )
        slug = re.sub(r"[^a-z0-9]+", "-", (st.ticket.summary if st.ticket else "").lower()).strip("-")[:40]
        st.branch = (
            st.branch
            or f"{self.s.project.branch_prefix}{ticket_slug(st.ticket_key).replace('_', '-')}-{slug}".rstrip("-")
        )
        git.checkout_new(st.branch, self.s.project.base_branch)
        self._checkpoint()

    def _final_status(self) -> str:
        results = final_results(self.state)
        open_ = [r for r in results if r.outcome in (Outcome.failed, Outcome.error)]
        if not open_:
            return "passed" if any(r.outcome == Outcome.passed for r in results) else "needs_human"
        cats = latest_verdicts(self.state)
        found = {cats.get((r.node_id, r.device), "needs_human") for r in open_}
        if found == {"product_bug"}:
            return "product_bug"
        if found == {"test_defect"}:
            return "failed"  # heal budget exhausted
        return "needs_human"  # mixed, unclassified, or a persistent environment problem

    def _file_bugs(self) -> None:
        st, auto = self.state, self.s.autonomy
        if not auto.file_bugs:
            return
        results = {(r.node_id, r.device): r for r in final_results(st)}
        grouped = defaultdict(list)
        for report in st.triage:
            for v in report.verdicts:
                r = results.get((v.node_id, v.device))
                still_failing = r is not None and r.outcome in (Outcome.failed, Outcome.error)
                if (
                    v.category == FailureCategory.product_bug
                    and v.confidence >= auto.min_bug_confidence
                    and still_failing
                ):
                    grouped[v.node_id].append(v)
        for node_id, verdicts in grouped.items():
            # Keep the latest verdict per device.
            verdicts = list({v.device: v for v in verdicts}.values())
            failing = [results[(v.node_id, v.device)] for v in verdicts]
            bug = draft_bug(self.d.llm, st.ticket, verdicts, failing)
            st.bugs.append(bug)
            self._checkpoint()
            if not self.d.jira:
                continue
            project = self.s.jira.bug_project or st.ticket_key.split("-")[0]
            body = _bug_markdown(bug, st.ticket_key, node_id, failing)
            key = self.guard.run(
                f"create bug in {project}",
                bug.title,
                lambda bug=bug, body=body, project=project: self.d.jira.create_bug(
                    project, bug.title, body, self.s.jira.bug_labels, _jira_priority(bug.severity)
                ),
            )
            if not key:
                continue
            st.bug_keys.append(key)
            self._checkpoint()
            for r in failing:
                shot = r.artifacts.get("screenshot")
                if shot and Path(shot).is_file():
                    try:
                        self.d.jira.attach(key, Path(shot))
                    except RuntimeError as exc:
                        self.store.event("attach_failed", {"bug": key, "error": str(exc)})
            try:
                self.d.jira.link(st.ticket_key, key)
            except RuntimeError as exc:
                self.store.event("link_failed", {"bug": key, "error": str(exc)})

    def _open_pr(self) -> None:
        st, s = self.state, self.s
        git = self.d.git
        if git is None or not st.files_changed or not st.branch:
            return
        if st.status == "product_bug" and not s.autonomy.open_pr_on_product_bug:
            return
        sha = git.commit(
            [f for f in st.files_changed if (s.repo_root / f).exists()],
            f"test({st.ticket_key}): automated mobile tests for {st.ticket.summary if st.ticket else st.ticket_key}\n\n"
            f"Generated and validated on Sauce Labs by qa-harness (run {st.run_id}).",
        )
        self.store.event("commit", {"sha": sha})
        if not self.d.github:
            self.store.event("side_effect_skipped", {"action": "push and open PR", "reason": "GitHub not configured"})
            return
        if not self.guard.run("push branch", st.branch, lambda: git.push(st.branch) or True):
            return
        prefix = {"passed": "", "product_bug": "[bug found] "}.get(st.status, "[needs review] ")
        title = f"{prefix}test({st.ticket_key}): {st.ticket.summary if st.ticket else ''}".strip()
        body = render_report(st) + f"\n\nJira: {st.ticket.url if st.ticket else st.ticket_key}"
        pr = self.guard.run(
            "open pull request",
            title,
            lambda: self.d.github.open_or_update_pr(st.branch, s.project.base_branch, title, body),
        )
        if pr:
            st.pr_url = pr.get("html_url")


def _jira_priority(severity: str) -> str | None:
    return {"blocker": "Highest", "critical": "High", "major": "Medium", "minor": "Low", "trivial": "Lowest"}.get(
        severity.lower()
    )


def _bug_markdown(bug, ticket_key: str, node_id: str, results) -> str:
    lines = [
        f"Found by automated QA while verifying {ticket_key}.",
        "",
        "## Environment",
        bug.environment,
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
        *[f"- {c}" for c in bug.violated_criteria],
        "",
        "## Evidence",
        *[f"- {e}" for e in bug.evidence],
        "",
        "## Sauce Labs sessions",
        *[f"- {r.device}: [{r.sauce_url}]({r.sauce_url})" for r in results if r.sauce_url],
        "",
        f"Automated test: `{node_id}`",
    ]
    return "\n".join(lines)


def new_state(ticket_key: str) -> RunState:
    return RunState(
        run_id=RunStore.new_run_id(ticket_key),
        ticket_key=ticket_key,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
