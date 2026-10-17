"""Run records, audit log, the write gate, and cross-run flake memory."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from .config import AutonomyMode
from .models import Outcome, RunSummary, TestResult

T = TypeVar("T")


class QaRun(BaseModel):
    """All Sauce Labs attempts for one ticket's scenarios, plus what was published from them."""

    run_id: str
    ticket_key: str
    created_at: str
    scenario_ids: list[str] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=list)
    attempts: list[RunSummary] = Field(default_factory=list)
    bugs: dict[str, str] = Field(default_factory=dict, description="scenario id -> Jira bug key")
    pr_url: str | None = None
    jira_reported: bool = False

    def final_results(self) -> list[TestResult]:
        """Latest result per (scenario, device) across attempts."""
        latest: dict[tuple[str, str], TestResult] = {}
        for attempt in self.attempts:
            for r in attempt.results:
                latest[(r.node_id, r.device)] = r
        return sorted(latest.values(), key=lambda r: (r.node_id, r.device))

    def status(self) -> str:
        results = self.final_results()
        if not results:
            return "not_run"
        failing = [r for r in results if r.outcome in (Outcome.failed, Outcome.error)]
        if failing:
            return "failed"
        return "passed" if any(r.outcome == Outcome.passed for r in results) else "skipped"


class RunStore:
    """One directory per run: run.json, audit.jsonl, attempt<N>/<device>/ evidence."""

    def __init__(self, runs_root: Path, run_id: str):
        self.root = runs_root
        self.dir = runs_root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._audit = self.dir / "audit.jsonl"

    @staticmethod
    def new(runs_root: Path, ticket_key: str) -> tuple[RunStore, QaRun]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run = QaRun(run_id=f"{ticket_key}-{stamp}", ticket_key=ticket_key, created_at=stamp)
        store = RunStore(runs_root, run.run_id)
        store.save(run)
        return store, run

    @staticmethod
    def latest_id(runs_root: Path, ticket_key: str) -> str | None:
        runs = sorted(runs_root.glob(f"{ticket_key}-*/run.json"), key=lambda p: p.stat().st_mtime)
        return runs[-1].parent.name if runs else None

    def save(self, run: QaRun) -> None:
        tmp = self.dir / "run.json.tmp"
        tmp.write_text(run.model_dump_json(indent=2))
        tmp.replace(self.dir / "run.json")

    def load(self) -> QaRun:
        path = self.dir / "run.json"
        if not path.exists():
            raise FileNotFoundError(f"No run {self.dir.name}")
        return QaRun.model_validate_json(path.read_text())

    def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        line = {"ts": time.time(), "kind": kind, **(data or {})}
        with self._audit.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")


class Guard:
    """Every Jira/GitHub write goes through here. In dry_run it is logged and skipped.

    Interactive approval is Copilot's job: VS Code asks before each MCP tool call unless the user
    auto-approves it, so the harness itself never prompts."""

    def __init__(self, mode: AutonomyMode, store: RunStore):
        self.mode = mode
        self.store = store

    def run(self, action: str, detail: str, fn: Callable[[], T]) -> T | None:
        if self.mode == AutonomyMode.dry_run:
            self.store.event("side_effect_skipped", {"action": action, "detail": detail, "reason": "dry_run"})
            print(f"[dry-run] would {action}: {detail}", file=sys.stderr)
            return None
        self.store.event("side_effect", {"action": action, "detail": detail})
        return fn()


class FlakeMemory:
    """Per scenario@device outcome history across runs, to tell chronic flakes from new failures."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, list[dict[str, Any]]] = json.loads(path.read_text()) if path.exists() else {}

    def record(self, summary: RunSummary) -> None:
        for r in summary.results:
            hist = self.data.setdefault(f"{r.node_id}@{r.device}", [])
            hist.append({"ts": int(time.time()), "outcome": r.outcome.value})
            del hist[:-30]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))

    def history(self, node_id: str, device: str) -> list[str]:
        return [h["outcome"] for h in self.data.get(f"{node_id}@{device}", [])]

    def flake_rate(self, node_id: str, device: str) -> float | None:
        hist = self.history(node_id, device)
        if len(hist) < 3:
            return None
        flips = sum(1 for a, b in zip(hist, hist[1:], strict=False) if a != b)
        return flips / (len(hist) - 1)
