"""The operations behind the Copilot tools, end to end over mocked Jira/GitHub and a real local git remote."""

from __future__ import annotations

import subprocess

import pytest

from qa_harness import ops
from qa_harness.config import AutonomyMode
from qa_harness.models import BugReport, Outcome

from .fakes import FEATURE, FEATURE_TEXT, NODE, ScriptedExecutor, make_services

BUG = BugReport(
    title="Error banner missing for wrong password",
    severity="Major",
    steps_to_reproduce=["Open the app", "Enter a wrong password", "Tap Sign in"],
    expected="An 'invalid password' banner",
    actual="Nothing is shown",
    violated_criteria=["AC1"],
    evidence=['no element with content-desc="login-error" in page source'],
)


def remote_heads(repo) -> str:
    return subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=repo, capture_output=True, text=True).stdout


def write_feature(repo):
    path = repo / FEATURE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FEATURE_TEXT)


def test_discover_then_run_and_rerun_in_same_run(sandbox_repo):
    write_feature(sandbox_repo)
    executor = ScriptedExecutor([{"pixel": Outcome.failed}, {}])
    svc = make_services(sandbox_repo, executor)

    assert f"OK   {NODE}" in ops.discover(svc, [FEATURE])

    run, text = ops.run_scenarios(svc, "APP-1", [NODE])
    assert executor.calls[0] == {"iphone": [NODE], "pixel": [NODE]}
    assert "FAILED  Wrong password shows error on pixel" in text
    assert "hint: test_defect (likely)" in text
    assert run.status() == "failed"

    run2, _ = ops.run_scenarios(svc, "APP-1", [NODE], devices=["pixel"], run_id=run.run_id)
    assert run2.run_id == run.run_id and len(run2.attempts) == 2
    assert run2.status() == "passed"  # latest result per device wins


def test_run_validation(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{}]))
    with pytest.raises(ValueError, match="Unknown device"):
        ops.run_scenarios(svc, "APP-1", [NODE], devices=["nokia"])
    with pytest.raises(ValueError, match="No scenario ids"):
        ops.run_scenarios(svc, "APP-1", [])
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])
    with pytest.raises(ValueError, match="belongs to APP-1"):
        ops.run_scenarios(svc, "APP-2", [NODE], run_id=run.run_id)


def test_failure_evidence_has_locator_inventory(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]))
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])
    text = ops.failure_evidence(svc, run.run_id, NODE, "pixel")
    assert 'Button resource-id="com.app:id/sign_in" content-desc="sign-in-button" text="Sign in"' in text
    assert "Other devices: iphone=passed" in text
    assert "https://app.saucelabs.com/tests/job-1-pixel" in text
    assert ".qa_runs/" in text  # repo-relative paths Copilot can open


def test_bug_only_for_recorded_failure_and_only_once(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]))
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])

    with pytest.raises(ValueError, match="not failing"):
        ops.file_bug(svc, run.run_id, "src/test/resources/features/other.feature:3", BUG)

    assert "Filed APP-99" in ops.file_bug(svc, run.run_id, NODE, BUG)
    assert "Already filed as APP-99" in ops.file_bug(svc, run.run_id, NODE, BUG)

    rec = svc.recorder
    created = rec.body("POST", "/rest/api/3/issue")
    assert created["fields"]["summary"] == BUG.title and created["fields"]["priority"] == {"name": "Medium"}
    assert "job-1-pixel" in str(created["fields"]["description"])
    assert ("POST", "/rest/api/3/issue/APP-99/attachments") in rec.writes()
    assert ("POST", "/rest/api/3/issueLink") in rec.writes()
    assert [p for m, p in rec.writes() if p.endswith("/rest/api/3/issue")] == ["/rest/api/3/issue"]  # once


def test_publish_uses_recorded_status(sandbox_repo):
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]))
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])
    out = ops.publish_to_jira(svc, run.run_id)
    assert "transitioned to QA Failed" in out
    rec = svc.recorder
    assert rec.body("POST", "/transitions") == {"transition": {"id": "2"}}
    comment = str(rec.body("POST", "/issue/APP-1/comment"))
    assert "failed" in comment and "job-1-pixel" in comment
    assert ("PUT", "/rest/api/3/issue/APP-1") in rec.writes()  # done label


def test_open_pr_commits_only_test_project(sandbox_repo):
    write_feature(sandbox_repo)
    (sandbox_repo / "README.md").write_text("unrelated local edit\n")
    svc = make_services(sandbox_repo, ScriptedExecutor([{}]))
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])

    out = ops.open_pull_request(svc, run.run_id)

    assert out == "Pull request: https://github.com/o/r/pull/7"
    assert "refs/heads/qa/app-1" in remote_heads(sandbox_repo)
    committed = svc.git.run("show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed == [FEATURE]
    assert svc.git.changed_files(".") == ["README.md"]  # left alone
    pr = svc.recorder.body("POST", "/pulls")
    assert pr["head"] == "qa/app-1" and pr["base"] == "main" and pr["draft"] is True
    assert "All scenarios pass" in pr["body"]


def test_open_pr_without_token_returns_compare_link(sandbox_repo):
    write_feature(sandbox_repo)
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]), github=False)
    svc.settings.github.repo = "o/r"
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])
    out = ops.open_pull_request(svc, run.run_id)
    assert "https://github.com/o/r/compare/main...qa/app-1?expand=1" in out
    assert "Title: [failed] test(APP-1)" in out


def test_dry_run_never_writes_externally(sandbox_repo):
    write_feature(sandbox_repo)
    svc = make_services(sandbox_repo, ScriptedExecutor([{"pixel": Outcome.failed}]), mode=AutonomyMode.dry_run)
    run, _ = ops.run_scenarios(svc, "APP-1", [NODE])
    assert "[dry-run] Would file" in ops.file_bug(svc, run.run_id, NODE, BUG)
    assert "[dry-run]" in ops.publish_to_jira(svc, run.run_id)
    assert "not pushed" in ops.open_pull_request(svc, run.run_id)
    assert svc.recorder.writes() == []
    assert "qa/app-1" not in remote_heads(sandbox_repo)


def test_exclude_done_label():
    jql = ops.exclude_done("project = APP ORDER BY priority DESC", "qa-ai-done")
    assert jql == '(project = APP) AND (labels IS EMPTY OR labels != "qa-ai-done") ORDER BY priority DESC'
