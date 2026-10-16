"""Run state checkpointing, audit logging, side-effect gating, and cross-run memory."""

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
from .models import (
    BugReport,
    GenerationResult,
    RunSummary,
    TestPlan,
    Ticket,
    TriageReport,
)

T = TypeVar("T")

STAGES = ["ingest", "plan", "generate", "execute", "publish", "report"]


class RunState(BaseModel):
    run_id: str
    ticket_key: str
    started_at: str
    completed_stages: list[str] = Field(default_factory=list)
    status: str = "running"  # running | passed | product_bug | failed | needs_human | error
    branch: str | None = None
    ticket: Ticket | None = None
    plan: TestPlan | None = None
    generation: GenerationResult | None = None
    runs: list[RunSummary] = Field(default_factory=list)
    triage: list[TriageReport] = Field(default_factory=list)
    bugs: list[BugReport] = Field(default_factory=list)
    bug_keys: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    pr_url: str | None = None
    cost: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @property
    def last_run(self) -> RunSummary | None:
        return self.runs[-1] if self.runs else None


class RunStore:
    """One directory per run: state.json (checkpoint), audit.jsonl, artifacts/."""

    def __init__(self, runs_root: Path, run_id: str):
        self.dir = runs_root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.dir / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self._audit = self.dir / "audit.jsonl"

    @staticmethod
    def new_run_id(ticket_key: str) -> str:
        return f"{ticket_key}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    def save(self, state: RunState) -> None:
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(state.model_dump_json(indent=2))
        tmp.replace(self.dir / "state.json")

    def load(self) -> RunState:
        return RunState.model_validate_json((self.dir / "state.json").read_text())

    def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        line = {"ts": time.time(), "kind": kind, **(data or {})}
        with self._audit.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")

    def write_json(self, name: str, data: Any) -> Path:
        p = self.dir / name
        p.write_text(json.dumps(data, indent=2, default=str))
        return p


class Guard:
    """Applies the autonomy policy to every side effect that leaves the machine."""

    def __init__(self, mode: AutonomyMode, store: RunStore, ask: Callable[[str], str] | None = None):
        self.mode = mode
        self.store = store
        self.ask = ask or (lambda prompt: input(prompt))

    def allow(self, action: str, detail: str = "") -> bool:
        if self.mode == AutonomyMode.dry_run:
            self.store.event("side_effect_skipped", {"action": action, "detail": detail, "reason": "dry_run"})
            print(f"[dry-run] would {action}: {detail}", file=sys.stderr)
            return False
        if self.mode == AutonomyMode.supervised:
            if not sys.stdin.isatty():
                self.store.event("side_effect_skipped", {"action": action, "reason": "supervised, no tty"})
                return False
            answer = self.ask(f"\nApprove: {action}\n  {detail}\n[y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                self.store.event("side_effect_declined", {"action": action, "detail": detail})
                return False
        self.store.event("side_effect", {"action": action, "detail": detail})
        return True

    def run(self, action: str, detail: str, fn: Callable[[], T]) -> T | None:
        return fn() if self.allow(action, detail) else None


class FlakeMemory:
    """Per-test history across runs, used to tell chronic flakes from new failures."""

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

    def flake_rate(self, node_id: str, device: str) -> float | None:
        hist = self.data.get(f"{node_id}@{device}", [])
        if len(hist) < 3:
            return None
        flips = sum(1 for a, b in zip(hist, hist[1:], strict=False) if a["outcome"] != b["outcome"])
        return flips / (len(hist) - 1)
