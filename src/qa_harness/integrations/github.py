"""Git operations (local CLI) and GitHub REST for pull requests."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import httpx2 as httpx

from ..config import GitHubConfig


class Git:
    def __init__(self, repo_root: Path):
        self.root = repo_root

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def is_dirty(self, paths: list[str] | None = None) -> bool:
        return bool(self.run("status", "--porcelain", *(["--", *paths] if paths else [])))

    def checkout_new(self, branch: str, base: str) -> None:
        self.run("fetch", "origin", base, check=False)
        start = f"origin/{base}" if self.run("rev-parse", "--verify", f"origin/{base}", check=False) else base
        self.run("checkout", "-B", branch, start)

    def commit(self, paths: list[str], message: str) -> str | None:
        self.run("add", "--", *paths)
        if not self.run("diff", "--cached", "--name-only"):
            return None
        self.run("commit", "-m", message)
        return self.run("rev-parse", "HEAD")

    def push(self, branch: str) -> None:
        self.run("push", "-u", "origin", branch)

    def remote_repo(self) -> str | None:
        url = self.run("remote", "get-url", "origin", check=False)
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
        return m.group(1) if m else None


class GitHubClient:
    def __init__(self, cfg: GitHubConfig, token: str, repo: str, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.repo = repo
        self.http = httpx.Client(
            base_url=cfg.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            transport=transport,
        )

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub {method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    def find_open_pr(self, head_branch: str) -> dict[str, Any] | None:
        owner = self.repo.split("/")[0]
        prs = self._req("GET", f"/repos/{self.repo}/pulls", params={"head": f"{owner}:{head_branch}", "state": "open"})
        return prs[0] if prs else None

    def open_or_update_pr(self, head: str, base: str, title: str, body: str) -> dict[str, Any]:
        existing = self.find_open_pr(head)
        if existing:
            return self._req("PATCH", f"/repos/{self.repo}/pulls/{existing['number']}", json={"body": body})
        pr = self._req(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": self.cfg.draft_pr},
        )
        number = pr["number"]
        if self.cfg.labels:
            self._req("POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": self.cfg.labels})
        if self.cfg.reviewers:
            self._req(
                "POST", f"/repos/{self.repo}/pulls/{number}/requested_reviewers", json={"reviewers": self.cfg.reviewers}
            )
        return pr
