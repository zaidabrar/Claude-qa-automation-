"""Adapter for the Java test suite: Maven + TestNG + Cucumber + Appium.

Scenario ids are ``<feature path relative to the Maven project>:<line>``, exactly what
``-Dcucumber.features=...`` accepts, so any subset can be re-run on any device.
The suite reports results through ``com.qa.mobile.support.QaResultsPlugin`` into
``$QA_RESULTS_FILE``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Discovery:
    ids: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)  # scenario id -> undefined/ambiguous step
    compiled: bool = True
    output: str = ""

    def summary(self) -> str:
        if not self.compiled:
            return f"COMPILATION FAILED\n{self.output[-6000:]}"
        lines = [f"{len(self.ids)} scenario(s) discovered, {len(self.problems)} with problems"]
        lines += [f"  OK   {i}" for i in self.ids if i not in self.problems]
        lines += [f"  FAIL {i}: {msg}" for i, msg in self.problems.items()]
        return "\n".join(lines)


class TestFramework(Protocol):
    project_dir: Path

    def compile(self) -> tuple[bool, str]: ...
    def discover(self, features: list[str] | None = None) -> Discovery: ...
    def run(self, scenario_ids: list[str], env: dict[str, str], out_dir: Path, timeout: int) -> str: ...
    def to_project_path(self, repo_relative: str) -> str | None: ...
    def source_path(self, scenario_id: str) -> Path: ...


class CucumberMaven:
    __test__ = False

    def __init__(self, project_dir: Path, repo_root: Path, mvn: str = "mvn", extra_args: list[str] | None = None):
        self.project_dir = project_dir.resolve()
        self.repo_root = repo_root.resolve()
        self.mvn = mvn
        self.extra_args = extra_args or []

    def _mvn(self, *args: str, env: dict[str, str] | None = None, timeout: int = 900) -> tuple[int, str]:
        cmd = [self.mvn, "-B", "-q", *self.extra_args, *args]
        try:
            proc = subprocess.run(
                cmd, cwd=self.project_dir, env=env or os.environ.copy(), capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            return 124, f"{' '.join(cmd)} timed out after {timeout}s\n{exc.stdout or ''}"
        except FileNotFoundError:
            return 127, f"{self.mvn} not found; install Maven or set project.maven_cmd"
        out = "\n".join(line for line in (proc.stdout + proc.stderr).splitlines() if "JAVA_TOOL_OPTIONS" not in line)
        return proc.returncode, out

    # ------------------------------------------------------------------ build

    def compile(self) -> tuple[bool, str]:
        code, out = self._mvn("test-compile")
        return code == 0, out[-12000:] or "compiled"

    def discover(self, features: list[str] | None = None) -> Discovery:
        """Compile, then Cucumber dry-run: binds every step without starting a device."""
        ok, out = self.compile()
        if not ok:
            return Discovery(compiled=False, output=out)
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "dry.json"
            env = {**os.environ, "QA_RESULTS_FILE": str(results)}
            args = ["surefire:test", "-Dcucumber.execution.dry-run=true"]
            if features:
                args.append(f"-Dcucumber.features={','.join(features)}")
            _, log = self._mvn(*args, env=env)
            if not results.exists():
                return Discovery(compiled=True, output=log[-8000:])
            records = json.loads(results.read_text())
        ids = [r["node_id"] for r in records]
        problems = {r["node_id"]: r["message"] for r in records if r["outcome"] == "error"}
        return Discovery(ids=ids, problems=problems, compiled=True, output=log[-4000:])

    # ------------------------------------------------------------------ execution

    def run(self, scenario_ids: list[str], env: dict[str, str], out_dir: Path, timeout: int) -> str:
        """Run already-compiled scenarios. Safe to call concurrently (one call per device)."""
        _, log = self._mvn(
            "surefire:test",
            f"-Dcucumber.features={','.join(scenario_ids)}",
            f"-Dsurefire.reportsDirectory={out_dir / 'surefire-reports'}",
            env=env,
            timeout=timeout,
        )
        return log

    # ------------------------------------------------------------------ paths

    def to_project_path(self, repo_relative: str) -> str | None:
        p = (self.repo_root / repo_relative).resolve()
        try:
            return str(p.relative_to(self.project_dir))
        except ValueError:
            return None

    def source_path(self, scenario_id: str) -> Path:
        return self.project_dir / scenario_id.rsplit(":", 1)[0]
