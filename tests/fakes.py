"""Test doubles: a scripted Sauce executor, a Maven-free framework, and HTTP recorders."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx2 as httpx

from qa_harness.config import (
    AutonomyMode,
    DeviceConfig,
    GitHubConfig,
    JiraConfig,
    Secrets,
    Settings,
    TransitionConfig,
)
from qa_harness.framework import CucumberMaven, Discovery
from qa_harness.integrations.github import Git, GitHubClient
from qa_harness.integrations.jira import JiraClient
from qa_harness.models import Outcome, RunSummary, TestResult
from qa_harness.services import Services

FEATURE = "mobile-tests/src/test/resources/features/app_1/login.feature"
NODE = "src/test/resources/features/app_1/login.feature:5"
FEATURE_TEXT = """@APP-1
Feature: Login errors

  @TC-01 @P1
  Scenario: Wrong password shows error
    Given the login screen is displayed
"""

ANDROID_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <android.widget.FrameLayout bounds="[0,0][1080,2400]">
    <android.widget.EditText resource-id="com.app:id/user" content-desc="username-input" text="" clickable="true"/>
    <android.widget.Button resource-id="com.app:id/sign_in" content-desc="sign-in-button" text="Sign in"
        clickable="true"/>
    <android.view.View bounds="[0,0][10,10]"/>
  </android.widget.FrameLayout>
</hierarchy>"""

DEVICES = [
    DeviceConfig(name="pixel", platform="android", device_name="Google Pixel 8"),
    DeviceConfig(name="iphone", platform="ios", device_name="iPhone 15"),
]


class FakeFramework(CucumberMaven):
    """Real path handling; compile/discover simulated by scanning feature files (no Maven)."""

    def compile(self) -> tuple[bool, str]:
        return True, "compiled"

    def discover(self, features=None) -> Discovery:
        ids = []
        for rel in features or []:
            for n, line in enumerate((self.project_dir / rel).read_text().splitlines(), 1):
                if line.strip().startswith(("Scenario:", "Scenario Outline:")):
                    ids.append(f"{rel}:{n}")
        return Discovery(ids=ids)


class ScriptedExecutor:
    """Returns scripted outcomes per attempt; failures get a real page source + screenshot on disk."""

    def __init__(self, outcomes: list[dict[str, Outcome]], message: str = "NoSuchElementException: login-button"):
        self.outcomes = outcomes
        self.message = message
        self.calls: list[dict[str, list[str]]] = []
        self.root: Path | None = None

    def run(self, targets, attempt, build) -> RunSummary:
        self.calls.append(targets)
        script = self.outcomes[len(self.calls) - 1]
        results = []
        for device, ids in targets.items():
            for node in ids:
                outcome = script.get(device, Outcome.passed)
                artifacts = {}
                if outcome != Outcome.passed:
                    d = self.root / f"attempt{attempt}" / device
                    d.mkdir(parents=True, exist_ok=True)
                    (d / "page_source.xml").write_text(ANDROID_SOURCE)
                    (d / "screenshot.png").write_bytes(b"\x89PNG fake")
                    artifacts = {"page_source": str(d / "page_source.xml"), "screenshot": str(d / "screenshot.png")}
                results.append(
                    TestResult(
                        node_id=node,
                        name="Wrong password shows error",
                        device=device,
                        outcome=outcome,
                        message="" if outcome == Outcome.passed else self.message,
                        sauce_job_id=f"job-{attempt}-{device}",
                        sauce_url=f"https://app.saucelabs.com/tests/job-{attempt}-{device}",
                        artifacts=artifacts,
                    )
                )
        return RunSummary(attempt=attempt, results=results)


class Recorder:
    """Mock HTTP transport for Jira + GitHub that records every call."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content[:1] == b"{" else {}
        self.calls.append((request.method, request.url.path, body))
        p = request.url.path
        if p.endswith("/transitions") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "transitions": [
                        {"id": "1", "name": "QA Passed", "to": {"name": "QA Passed"}},
                        {"id": "2", "name": "QA Failed", "to": {"name": "QA Failed"}},
                    ]
                },
            )
        if p.endswith("/rest/api/3/issue") and request.method == "POST":
            return httpx.Response(201, json={"key": "APP-99"})
        if p.endswith("/pulls") and request.method == "GET":
            return httpx.Response(200, json=[])
        if p.endswith("/pulls") and request.method == "POST":
            return httpx.Response(201, json={"number": 7, "html_url": "https://github.com/o/r/pull/7"})
        return httpx.Response(200, json={})

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls if m != "GET"]

    def body(self, method: str, suffix: str) -> dict:
        return next(b for m, p, b in self.calls if m == method and p.endswith(suffix))


@dataclass
class FakeServices(Services):
    scripted: ScriptedExecutor | None = None
    recorder: Recorder = field(default_factory=Recorder)

    def executor(self, artifacts_root):
        self.scripted.root = artifacts_root
        return self.scripted


def make_services(
    repo: Path, executor: ScriptedExecutor, mode=AutonomyMode.autonomous, github: bool = True
) -> FakeServices:
    settings = Settings()
    settings.project.repo_root = repo
    settings.sauce.devices = DEVICES
    settings.autonomy.mode = mode
    settings.jira = JiraConfig(
        base_url="https://x.atlassian.net", transitions=TransitionConfig(on_pass="QA Passed", on_fail="QA Failed")
    )
    rec = Recorder()
    return FakeServices(
        settings=settings,
        secrets=Secrets(),
        framework=FakeFramework(repo / "mobile-tests", repo),
        jira=JiraClient(settings.jira, "e", "t", transport=httpx.MockTransport(rec)),
        git=Git(repo),
        github=GitHubClient(GitHubConfig(), "tok", "o/r", transport=httpx.MockTransport(rec)) if github else None,
        scripted=executor,
        recorder=rec,
    )
