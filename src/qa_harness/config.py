"""Harness configuration.

Non-secret settings live in ``qa_harness.yaml``; credentials come only from the
environment so they never land in the repo, a checkpoint, or a prompt.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AutonomyMode(str, Enum):
    autonomous = "autonomous"  # every side effect runs without asking
    supervised = "supervised"  # side effects outside the repo (Jira writes, bugs, PR) ask on the terminal
    dry_run = "dry_run"  # nothing leaves the machine; side effects are logged only


class ProjectConfig(BaseModel):
    repo_root: Path = Path(".")
    tests_dir: str = "mobile-tests"  # the Maven project (Appium + TestNG + Cucumber)
    maven_cmd: str = "mvn"
    maven_args: list[str] = Field(default_factory=list)  # e.g. ["-s", "ci-settings.xml"]
    base_branch: str = "main"
    branch_prefix: str = "qa/"
    runs_dir: str = ".qa_runs"


class LLMConfig(BaseModel):
    model: str = "claude-opus-5-5"
    effort: str = "high"  # low | medium | high | xhigh | max
    triage_effort: str = "high"
    max_tokens: int = 64000
    max_agent_turns: int = 60
    max_usd_per_run: float = 20.0
    # Route policy declines to Anthropic's recommended fallback model server-side.
    fallbacks: bool = True


class TransitionConfig(BaseModel):
    on_start: str | None = None
    on_pass: str | None = None
    on_fail: str | None = None


class JiraConfig(BaseModel):
    base_url: str = ""
    ready_jql: str = 'status = "Ready for QA" AND labels = "qa-ai" ORDER BY priority DESC'
    acceptance_criteria_field: str | None = None  # e.g. customfield_10042
    transitions: TransitionConfig = TransitionConfig()
    bug_project: str | None = None  # defaults to the ticket's project
    bug_issue_type: str = "Bug"
    bug_labels: list[str] = Field(default_factory=lambda: ["qa-ai-found"])
    done_label: str = "qa-ai-done"


class DeviceConfig(BaseModel):
    name: str  # short id used in reports and Sauce build names
    platform: str  # android | ios
    device_name: str  # Sauce device name or regex, e.g. "Google Pixel.*"
    platform_version: str = ""
    real_device: bool = True
    automation_name: str | None = None  # defaults: UiAutomator2 / XCUITest
    extra_capabilities: dict = Field(default_factory=dict)


class SauceConfig(BaseModel):
    region: str = "us-west-1"  # us-west-1 | eu-central-1 | us-east-4
    # Either a local path to .apk/.ipa/.aab (uploaded each run) or an existing
    # storage reference such as "storage:filename=MyApp.apk".
    android_app: str | None = None
    ios_app: str | None = None
    appium_version: str = "latest"
    devices: list[DeviceConfig] = Field(default_factory=list)
    max_parallel: int = 4
    test_timeout_s: int = 1800
    build_prefix: str = "qa-ai"


class GitHubConfig(BaseModel):
    repo: str = ""  # owner/name; inferred from `git remote` when empty
    api_url: str = "https://api.github.com"
    draft_pr: bool = True
    reviewers: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=lambda: ["qa-automation", "ai-generated"])


class AutonomyConfig(BaseModel):
    mode: AutonomyMode = AutonomyMode.autonomous
    max_heal_attempts: int = 3
    max_env_retries: int = 1
    file_bugs: bool = True
    min_bug_confidence: float = 0.8
    transition_jira: bool = True
    open_pr_on_product_bug: bool = True  # the tests are still valuable: they reproduce the bug


class NotifyConfig(BaseModel):
    slack_webhook_env: str = "SLACK_WEBHOOK_URL"


class Settings(BaseModel):
    project: ProjectConfig = ProjectConfig()
    llm: LLMConfig = LLMConfig()
    jira: JiraConfig = JiraConfig()
    sauce: SauceConfig = SauceConfig()
    github: GitHubConfig = GitHubConfig()
    autonomy: AutonomyConfig = AutonomyConfig()
    notify: NotifyConfig = NotifyConfig()

    @property
    def repo_root(self) -> Path:
        return self.project.repo_root.resolve()

    @property
    def tests_root(self) -> Path:
        return self.repo_root / self.project.tests_dir

    @property
    def runs_root(self) -> Path:
        return self.repo_root / self.project.runs_dir


class Secrets(BaseModel):
    jira_email: str | None = None
    jira_token: str | None = None
    sauce_username: str | None = None
    sauce_access_key: str | None = None
    github_token: str | None = None
    slack_webhook: str | None = None

    @classmethod
    def from_env(cls, notify: NotifyConfig) -> Secrets:
        return cls(
            jira_email=os.environ.get("JIRA_EMAIL"),
            jira_token=os.environ.get("JIRA_API_TOKEN"),
            sauce_username=os.environ.get("SAUCE_USERNAME"),
            sauce_access_key=os.environ.get("SAUCE_ACCESS_KEY"),
            github_token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
            slack_webhook=os.environ.get(notify.slack_webhook_env),
        )


def load_settings(path: str | Path | None = None) -> Settings:
    candidates = [Path(path)] if path else [Path("qa_harness.yaml"), Path("qa_harness.yml")]
    for candidate in candidates:
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text()) or {}
            settings = Settings.model_validate(data)
            # Relative repo_root is relative to the config file, not the cwd.
            if not settings.project.repo_root.is_absolute():
                settings.project.repo_root = (candidate.parent / settings.project.repo_root).resolve()
            return settings
    if path:
        raise FileNotFoundError(path)
    return Settings()
