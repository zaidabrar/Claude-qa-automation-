"""End-to-end pipeline scenarios with scripted LLM/Sauce and mocked Jira/GitHub over a real local git remote."""

from __future__ import annotations

import json
import subprocess

import httpx2 as httpx
import pytest

from qa_harness.config import AutonomyMode, DeviceConfig, GitHubConfig, JiraConfig, Secrets, Settings, TransitionConfig
from qa_harness.integrations.github import Git, GitHubClient
from qa_harness.integrations.jira import JiraClient
from qa_harness.models import BugReport, FailureCategory, Outcome, TestPlan, Ticket, TriageReport
from qa_harness.pipeline import Deps, Pipeline, new_state
from qa_harness.state import Guard, RunStore

from .fakes import (
    BUG,
    NODE,
    TEST_FILE,
    FakeFramework,
    ScriptedExecutor,
    ScriptedLLM,
    make_plan,
    triage,
    verdict,
    write_test_via_tools,
)

DEVICES = [
    DeviceConfig(name="pixel", platform="android", device_name="Google Pixel 8"),
    DeviceConfig(name="iphone", platform="ios", device_name="iPhone 15"),
]
TICKET = Ticket(key="APP-1", summary="Login error message", acceptance_criteria="AC1: wrong password shows error")


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content and b"{" in request.content[:1] else {}
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


def build(repo, llm, executor, mode=AutonomyMode.autonomous):
    settings = Settings()
    settings.project.repo_root = repo
    settings.sauce.devices = DEVICES
    settings.autonomy.mode = mode
    settings.jira = JiraConfig(
        base_url="https://x.atlassian.net", transitions=TransitionConfig(on_pass="QA Passed", on_fail="QA Failed")
    )
    rec = Recorder()
    deps = Deps(
        settings=settings,
        secrets=Secrets(),
        llm=llm,
        framework=FakeFramework(repo / "mobile-tests", repo),
        executor=executor,
        load_ticket=lambda key: TICKET,
        jira=JiraClient(settings.jira, "e", "t", transport=httpx.MockTransport(rec)),
        git=Git(repo),
        github=GitHubClient(GitHubConfig(), "tok", "o/r", transport=httpx.MockTransport(rec)),
    )
    state = new_state("APP-1")
    store = RunStore(settings.runs_root, state.run_id)
    return Pipeline(deps, store, state, Guard(mode, store)), rec, store


def remote_branches(repo) -> str:
    return subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=repo, capture_output=True, text=True).stdout


def test_happy_path_jira_to_pr(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.agent_queue.append(write_test_via_tools)
    executor = ScriptedExecutor(DEVICES, [{}])
    pipe, rec, store = build(sandbox_repo, llm, executor)

    state = pipe.run()

    assert state.status == "passed"
    assert state.completed_stages == ["ingest", "plan", "generate", "execute", "publish", "report"]
    assert executor.calls == [{"pixel": [NODE], "iphone": [NODE]}]
    assert state.files_changed == [TEST_FILE]
    assert state.branch.startswith("qa/app-1-login-error-message")
    assert state.branch in remote_branches(sandbox_repo)
    assert state.pr_url == "https://github.com/o/r/pull/7"
    pr = next(b for m, p, b in rec.calls if m == "POST" and p.endswith("/pulls"))
    assert pr["head"] == state.branch and pr["base"] == "main" and pr["draft"] is True
    assert "All generated tests pass" in pr["body"]
    writes = rec.writes()
    assert ("POST", "/rest/api/3/issue/APP-1/comment") in writes
    assert ("POST", "/rest/api/3/issue/APP-1/transitions") in writes
    assert ("PUT", "/rest/api/3/issue/APP-1") in writes  # done label
    assert (store.dir / "report.md").exists() and (store.dir / "plan.json").exists()
    assert llm.calls == ["TestPlan", "agent:GenerationResult"]


def test_self_heals_test_defect_then_passes(sandbox_repo):
    def heal(tools):
        out, err = tools.execute(
            "edit_file", {"path": TEST_FILE, "old_str": "Given the login screen", "new_str": "Given the healed screen"}
        )
        assert not err, out
        return _heal_result()

    llm = ScriptedLLM().queue(TestPlan, make_plan()).queue(TriageReport, triage(verdict(FailureCategory.test_defect)))
    llm.agent_queue += [write_test_via_tools, heal]
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.failed}, {}])
    pipe, rec, _ = build(sandbox_repo, llm, executor)

    state = pipe.run()

    assert state.status == "passed"
    assert executor.calls[1] == {"pixel": [NODE]}  # only the affected device is re-run
    assert "healed screen" in (sandbox_repo / TEST_FILE).read_text()
    assert not any(p.endswith("/rest/api/3/issue") for _, p in rec.writes())  # no bug filed


def _heal_result():
    from qa_harness.models import GeneratedFile, GenerationResult

    return GenerationResult(
        files=[GeneratedFile(path=TEST_FILE, purpose="fix")], test_node_ids=[NODE], summary="healed"
    )


def test_product_bug_is_filed_and_pr_flagged(sandbox_repo):
    llm = (
        ScriptedLLM()
        .queue(TestPlan, make_plan())
        .queue(TriageReport, triage(verdict(FailureCategory.product_bug, confidence=0.95)))
        .queue(BugReport, BUG)
    )
    llm.agent_queue.append(write_test_via_tools)
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.failed}])
    pipe, rec, _ = build(sandbox_repo, llm, executor)

    state = pipe.run()

    assert state.status == "product_bug"
    assert state.bug_keys == ["APP-99"]
    bug = next(b for m, p, b in rec.calls if m == "POST" and p.endswith("/rest/api/3/issue"))
    assert bug["fields"]["summary"] == BUG.title and bug["fields"]["priority"] == {"name": "Medium"}
    assert ("POST", "/rest/api/3/issueLink") in rec.writes()
    pr = next(b for m, p, b in rec.calls if m == "POST" and p.endswith("/pulls"))
    assert pr["title"].startswith("[bug found]") and "APP-99" in pr["body"]
    transition = next(b for m, p, b in rec.calls if m == "POST" and p.endswith("/transitions"))
    assert transition == {"transition": {"id": "2"}}  # QA Failed


def test_low_confidence_bug_is_not_filed(sandbox_repo):
    llm = (
        ScriptedLLM()
        .queue(TestPlan, make_plan())
        .queue(TriageReport, triage(verdict(FailureCategory.product_bug, confidence=0.5)))
    )
    llm.agent_queue.append(write_test_via_tools)
    pipe, rec, _ = build(sandbox_repo, llm, ScriptedExecutor(DEVICES, [{"pixel": Outcome.failed}]))
    state = pipe.run()
    assert state.status == "product_bug" and state.bug_keys == []


def test_environment_failure_is_retried_once(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan()).queue(TriageReport, triage(verdict(FailureCategory.environment)))
    llm.agent_queue.append(write_test_via_tools)
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.error}, {}])
    pipe, _, _ = build(sandbox_repo, llm, executor)
    state = pipe.run()
    assert state.status == "passed" and len(state.runs) == 2
    assert executor.calls[1] == {"pixel": [NODE]}


def test_heal_attempts_are_bounded(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.queue(TriageReport, *[triage(verdict(FailureCategory.test_defect)) for _ in range(4)])
    llm.agent_queue += [write_test_via_tools] + [lambda tools: _heal_result()] * 3
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.failed}] * 4)
    pipe, rec, _ = build(sandbox_repo, llm, executor)
    state = pipe.run()
    assert state.status == "failed"
    assert len(executor.calls) == 4  # initial + max_heal_attempts (3)
    pr = next(b for m, p, b in rec.calls if m == "POST" and p.endswith("/pulls"))
    assert pr["title"].startswith("[needs review]")


def test_dry_run_never_writes_externally(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.agent_queue.append(write_test_via_tools)
    pipe, rec, store = build(sandbox_repo, llm, ScriptedExecutor(DEVICES, [{}]), mode=AutonomyMode.dry_run)
    state = pipe.run()
    assert state.status == "passed"
    assert rec.writes() == []
    assert state.branch not in remote_branches(sandbox_repo)
    assert state.pr_url is None
    skipped = [json.loads(line) for line in (store.dir / "audit.jsonl").read_text().splitlines()]
    assert {"push branch", "comment on APP-1"} <= {
        e.get("action") for e in skipped if e["kind"] == "side_effect_skipped"
    }


def test_resume_continues_from_checkpoint(sandbox_repo):
    llm = ScriptedLLM()  # nothing queued: the plan stage fails
    llm.agent_queue.append(write_test_via_tools)
    pipe, _, store = build(sandbox_repo, llm, ScriptedExecutor(DEVICES, [{}]))
    with pytest.raises(AssertionError):
        pipe.run()
    saved = store.load()
    assert saved.status == "error" and saved.completed_stages == ["ingest"]

    llm.queue(TestPlan, make_plan())
    saved.status = "running"
    resumed = Pipeline(pipe.d, store, saved, pipe.guard).run()
    assert resumed.status == "passed"
    assert llm.calls.count("TestPlan") == 2  # first failed attempt + resume; ingest not repeated


def test_refuses_to_clobber_uncommitted_tests(sandbox_repo):
    (sandbox_repo / "mobile-tests" / "src" / "test" / "Wip.java").write_text("// local work\n")
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    pipe, _, _ = build(sandbox_repo, llm, ScriptedExecutor(DEVICES, [{}]))
    with pytest.raises(RuntimeError, match="uncommitted"):
        pipe.run()


def test_persistent_environment_failure_needs_human(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.queue(TriageReport, triage(verdict(FailureCategory.environment)), triage(verdict(FailureCategory.environment)))
    llm.agent_queue.append(write_test_via_tools)
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.error}, {"pixel": Outcome.error}])
    pipe, rec, _ = build(sandbox_repo, llm, executor)
    state = pipe.run()
    assert state.status == "needs_human" and len(executor.calls) == 2
    assert not any(p.endswith("/transitions") for m, p in rec.writes())  # a human decides


def test_heal_that_breaks_collection_reruns_old_ids(sandbox_repo):
    def break_file(tools):
        tools.execute("write_file", {"path": TEST_FILE, "content": "BROKEN\n"})
        return _heal_result()

    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.queue(TriageReport, *[triage(verdict(FailureCategory.test_defect)) for _ in range(4)])
    llm.agent_queue += [write_test_via_tools, break_file, *[lambda tools: _heal_result()] * 2]
    executor = ScriptedExecutor(DEVICES, [{"pixel": Outcome.failed}] * 4)
    pipe, _, _ = build(sandbox_repo, llm, executor)
    pipe.run()
    assert executor.calls[1] == {"pixel": [NODE]}  # not silently dropped


def test_resume_after_publish_crash_keeps_real_status(sandbox_repo):
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.agent_queue.append(write_test_via_tools)
    pipe, _, store = build(sandbox_repo, llm, ScriptedExecutor(DEVICES, [{}]))
    original = pipe._open_pr
    pipe._open_pr = lambda: (_ for _ in ()).throw(RuntimeError("network down"))
    with pytest.raises(RuntimeError):
        pipe.run()
    saved = store.load()
    assert saved.status == "error" and "execute" in saved.completed_stages
    saved.status = "running"
    pipe.state = saved
    pipe._open_pr = original
    assert pipe.run().status == "passed"
