"""Builds the integrations the tools need from config + environment. Missing credentials -> ``None``."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Secrets, Settings
from .executor import SauceExecutor
from .framework import CucumberMaven, TestFramework
from .integrations.github import Git, GitHubClient
from .integrations.jira import JiraClient
from .integrations.saucelabs import SauceClient


@dataclass
class Services:
    settings: Settings
    secrets: Secrets
    framework: TestFramework
    sauce: SauceClient | None = None
    jira: JiraClient | None = None
    git: Git | None = None
    github: GitHubClient | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        secrets = Secrets.from_env(settings.notify)
        framework = CucumberMaven(
            settings.tests_root, settings.repo_root, settings.project.maven_cmd, settings.project.maven_args
        )
        jira = sauce = github = None
        if settings.jira.base_url and secrets.jira_email and secrets.jira_token:
            jira = JiraClient(settings.jira, secrets.jira_email, secrets.jira_token)
        if secrets.sauce_username and secrets.sauce_access_key:
            sauce = SauceClient(settings.sauce, secrets.sauce_username, secrets.sauce_access_key)
        git = Git(settings.repo_root) if (settings.repo_root / ".git").exists() else None
        if git and secrets.github_token:
            repo = settings.github.repo or git.remote_repo()
            if repo:
                github = GitHubClient(settings.github, secrets.github_token, repo)
        return cls(settings, secrets, framework, sauce, jira, git, github)

    def executor(self, artifacts_root) -> SauceExecutor:
        return SauceExecutor(self.settings, self.secrets, self.sauce, self.framework, artifacts_root)

    def require_jira(self) -> JiraClient:
        if self.jira is None:
            raise RuntimeError("Jira is not configured: set jira.base_url, JIRA_EMAIL and JIRA_API_TOKEN")
        return self.jira

    def require_sauce(self) -> SauceClient:
        if self.sauce is None:
            raise RuntimeError("Sauce Labs is not configured: set SAUCE_USERNAME and SAUCE_ACCESS_KEY")
        return self.sauce
