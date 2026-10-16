from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sandbox_repo(tmp_path: Path) -> Path:
    """A throwaway git repo containing the real mobile-tests Maven project and a bare 'origin' remote."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo.mkdir()
    shutil.copytree(REPO / "mobile-tests", repo / "mobile-tests", ignore=shutil.ignore_patterns("target"))
    (repo / ".gitignore").write_text(".qa_runs/\ntarget/\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "qa@example.com")
    _git(repo, "config", "user.name", "QA Bot")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo
