"""Stage: run scenarios on the Sauce Labs device matrix, in parallel, and collect evidence."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import DeviceConfig, Secrets, Settings
from ..framework import TestFramework
from ..integrations.saucelabs import SauceClient
from ..models import Outcome, RunSummary, TestResult

Targets = dict[str, list[str]]  # device name -> scenario ids


class SauceExecutor:
    def __init__(
        self,
        settings: Settings,
        secrets: Secrets,
        sauce: SauceClient | None,
        framework: TestFramework,
        artifacts_root: Path,
    ):
        self.settings = settings
        self.secrets = secrets
        self.sauce = sauce
        self.framework = framework
        self.artifacts_root = artifacts_root
        self._apps: dict[str, str | None] | None = None

    def devices(self) -> list[DeviceConfig]:
        return self.settings.sauce.devices

    def _resolve_apps(self) -> dict[str, str | None]:
        # Upload once per run, not once per device or attempt.
        if self._apps is None:
            cfg = self.settings.sauce
            resolve = self.sauce.resolve_app if self.sauce else (lambda a: a)
            self._apps = {"android": resolve(cfg.android_app), "ios": resolve(cfg.ios_app)}
        return self._apps

    def run(self, targets: Targets, attempt: int, build: str) -> RunSummary:
        devices = {d.name: d for d in self.devices()}
        jobs = [(devices[name], ids) for name, ids in targets.items() if ids and name in devices]

        # Compile once, then run devices concurrently against the same classes.
        ok, compile_log = self.framework.compile()
        if not ok:
            return RunSummary(
                attempt=attempt,
                results=[
                    TestResult(
                        node_id=i,
                        device=d.name,
                        outcome=Outcome.error,
                        message="Compilation failed",
                        traceback=compile_log[-6000:],
                    )
                    for d, ids in jobs
                    for i in ids
                ],
            )

        with ThreadPoolExecutor(max_workers=max(1, self.settings.sauce.max_parallel)) as pool:
            batches = list(pool.map(lambda job: self._run_device(job[0], job[1], attempt, build), jobs))
        return RunSummary(attempt=attempt, results=[r for batch in batches for r in batch])

    def _run_device(self, device: DeviceConfig, ids: list[str], attempt: int, build: str) -> list[TestResult]:
        out_dir = (self.artifacts_root / f"attempt{attempt}" / device.name).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        results_file = out_dir / "results.json"
        env = {
            **os.environ,
            "QA_DEVICE": device.model_dump_json(),
            "QA_PLATFORM": device.platform.lower(),
            "QA_BUILD": build,
            "QA_ARTIFACTS_DIR": str(out_dir / "evidence"),
            "QA_RESULTS_FILE": str(results_file),
            "SAUCE_REGION": self.settings.sauce.region,
            "SAUCE_APPIUM_VERSION": self.settings.sauce.appium_version,
        }
        for platform, app in self._resolve_apps().items():
            if app:
                env[f"QA_APP_{platform.upper()}"] = app

        log = self.framework.run(ids, env, out_dir, self.settings.sauce.test_timeout_s)
        (out_dir / "run.log").write_text(log)

        results = parse_results(results_file, ids, device.name, log)
        for r in results:
            if r.sauce_job_id:
                r.sauce_url = SauceClient.job_url(r.sauce_job_id)
            if r.outcome in (Outcome.failed, Outcome.error) and r.sauce_job_id and self.sauce:
                try:
                    r.artifacts.update(
                        self.sauce.download_evidence(
                            r.sauce_job_id, device.real_device, out_dir / "sauce" / r.sauce_job_id
                        )
                    )
                except Exception as exc:  # evidence is best effort
                    r.artifacts["sauce_error"] = str(exc)
        return results


def parse_results(results_file: Path, ids: list[str], device: str, log: str) -> list[TestResult]:
    results: list[TestResult] = []
    if results_file.exists():
        try:
            results = [TestResult.model_validate(r) for r in json.loads(results_file.read_text())]
        except (json.JSONDecodeError, ValueError):
            results = []
    # A requested scenario with no result never ran: bad feature path, crash, or timeout.
    # Report it as an error so it can never be mistaken for a pass.
    seen = {r.node_id for r in results}
    results += [
        TestResult(node_id=i, device=device, outcome=Outcome.error, message="Did not run", traceback=log[-6000:])
        for i in ids
        if i not in seen
    ]
    return results
