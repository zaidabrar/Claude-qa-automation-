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

    def run(self, *args: str, check: bool = True, strip: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip() if strip else proc.stdout

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def is_dirty(self, paths: list[str] | None = None) -> bool:
        return bool(self.run("status", "--porcelain", *(["--", *paths] if paths else [])))

    def create_branch(self, branch: str) -> None:
        """Branch from the current HEAD, carrying uncommitted changes along (VS Code workflow)."""
        if self.run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
            self.run("checkout", branch)
        else:
            self.run("checkout", "-b", branch)

    def changed_files(self, path: str) -> list[str]:
        """Modified, added and untracked files under ``path`` (repo-relative)."""
        # Not stripped: porcelain lines start with a status column that may be a space.
        out = self.run("status", "--porcelain", "--untracked-files=all", "--", path, strip=False)
        files = []
        for line in out.splitlines():
            name = line[3:]
            if " -> " in name:  # rename
                name = name.split(" -> ", 1)[1]
            files.append(name.strip('"'))
        return files

    def commit(self, paths: list[str], message: str) -> str | None:
        self.run("add", "-A", "--", *paths)
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
