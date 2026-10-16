"""Test doubles: a scripted LLM, a scripted Sauce executor, and fake Anthropic responses."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from qa_harness.config import DeviceConfig, LLMConfig
from qa_harness.framework import CucumberMaven, Discovery
from qa_harness.llm import LLM, AgentOutcome
from qa_harness.models import (
    BugReport,
    CaseKind,
    FailureCategory,
    FailureVerdict,
    GeneratedFile,
    GenerationResult,
    Outcome,
    Platform,
    RunSummary,
    TestCase,
    TestPlan,
    TestResult,
    TestStep,
    TriageReport,
)
from qa_harness.tools import ToolRegistry

# ---------------------------------------------------------------------- canned data


def make_plan(key: str = "APP-1") -> TestPlan:
    return TestPlan(
        ticket_key=key,
        feature_summary="Login shows an error for a wrong password",
        risks=["error banner missing on iOS"],
        out_of_scope=[],
        ambiguities=["Exact error copy not specified; assumed it contains 'invalid'"],
        test_cases=[
            TestCase(
                id="TC-01",
                title="Wrong password shows error",
                kind=CaseKind.negative,
                priority=1,
                preconditions=["App freshly installed"],
                steps=[TestStep(action="Log in with a wrong password", expected="Error is shown")],
                platforms=[Platform.android],
                traces_to=["AC1"],
                automatable=True,
                automation_notes="",
            )
        ],
    )


TEST_FILE = "mobile-tests/src/test/resources/features/app_1/login.feature"
TEST_SOURCE = """@APP-1
Feature: Login errors

  @TC-01 @P1
  Scenario: Wrong password shows error
    Given the login screen is displayed
"""
NODE = "src/test/resources/features/app_1/login.feature:5"


def write_test_via_tools(tools: ToolRegistry) -> GenerationResult:
    out, err = tools.execute("write_file", {"path": TEST_FILE, "content": TEST_SOURCE})
    assert not err, out
    return GenerationResult(
        files=[GeneratedFile(path=TEST_FILE, purpose="feature")], test_node_ids=[NODE], summary="1 scenario"
    )


class FakeFramework(CucumberMaven):
    """Real path handling; compile/discover simulated by scanning feature files (no Maven needed).

    Any file under the project containing BROKEN makes compilation fail."""

    def compile(self) -> tuple[bool, str]:
        for f in self.project_dir.rglob("*"):
            if f.is_file() and f.suffix in (".java", ".feature") and "BROKEN" in f.read_text():
                return False, f"compilation error in {f.name}"
        return True, "compiled"

    def discover(self, features=None) -> Discovery:
        ok, out = self.compile()
        if not ok:
            return Discovery(compiled=False, output=out)
        ids = []
        for rel in features or []:
            for n, line in enumerate((self.project_dir / rel).read_text().splitlines(), 1):
                if line.strip().startswith(("Scenario:", "Scenario Outline:")):
                    ids.append(f"{rel}:{n}")
        return Discovery(ids=ids)


def verdict(category: FailureCategory, device: str = "pixel", confidence: float = 0.9) -> FailureVerdict:
    return FailureVerdict(
        node_id=NODE,
        device=device,
        category=category,
        confidence=confidence,
        root_cause=f"{category.value} root cause",
        evidence=["line from page source"],
        suggested_fix="do the thing",
    )


BUG = BugReport(
    title="Login error banner missing for wrong password",
    severity="Major",
    environment="Pixel 8, Android 14",
    steps_to_reproduce=["Open app", "Enter wrong password", "Tap Login"],
    expected="Error banner",
    actual="Nothing happens",
    evidence=["login-error absent from page source"],
    violated_criteria=["AC1"],
)

# ---------------------------------------------------------------------- scripted LLM


class ScriptedLLM(LLM):
    """Returns queued results per output type; agent calls run a callable against the real tools."""

    def __init__(self) -> None:
        super().__init__(LLMConfig(max_usd_per_run=100), client=SimpleNamespace())
        self.structured_queue: dict[type, list[Any]] = {}
        self.agent_queue: list[Callable[[ToolRegistry], Any]] = []
        self.calls: list[str] = []

    def queue(self, output_type: type, *values: Any) -> ScriptedLLM:
        self.structured_queue.setdefault(output_type, []).extend(values)
        return self

    def structured(self, *, system, content, output, effort=None):
        self.calls.append(output.__name__)
        q = self.structured_queue.get(output)
        if not q:
            raise AssertionError(f"unexpected structured call for {output.__name__}")
        return q.pop(0)

    def run_agent(self, *, system, task, tools, result_model, effort=None, max_turns=None):
        self.calls.append(f"agent:{result_model.__name__}")
        return AgentOutcome(result=self.agent_queue.pop(0)(tools), turns=1)


# ---------------------------------------------------------------------- scripted executor


class ScriptedExecutor:
    def __init__(self, devices: list[DeviceConfig], outcomes: list[dict[str, Outcome]]):
        self._devices = devices
        self.outcomes = outcomes  # one dict per attempt: device -> outcome
        self.calls: list[dict[str, list[str]]] = []

    def devices(self) -> list[DeviceConfig]:
        return self._devices

    def run(self, targets, attempt, build) -> RunSummary:
        self.calls.append(targets)
        script = self.outcomes[len(self.calls) - 1]
        results = []
        for device, ids in targets.items():
            for node in ids:
                outcome = script.get(device, Outcome.passed)
                results.append(
                    TestResult(
                        node_id=node,
                        device=device,
                        outcome=outcome,
                        message="" if outcome == Outcome.passed else "AssertionError: banner not found",
                        sauce_job_id=f"job-{attempt}-{device}",
                        sauce_url=f"https://app.saucelabs.com/tests/job-{attempt}-{device}",
                    )
                )
        return RunSummary(attempt=attempt, results=results)


def triage(*verdicts: FailureVerdict) -> TriageReport:
    return TriageReport(verdicts=list(verdicts), summary="triaged")


# ---------------------------------------------------------------------- fake Anthropic client


def usage(inp: int = 1000, out: int = 500) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use(id_: str, name: str, input_: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks, stop_reason: str = "tool_use", model: str = "claude-opus-5-5") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage(), model=model, stop_details=None)


class FakeAnthropic:
    """Mimics client.beta.messages.{stream,parse} with queued responses; records requests."""

    def __init__(self, responses: list[SimpleNamespace]):
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        outer = self

        class _Stream:
            def __init__(self, resp):
                self.resp = resp

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return self.resp

        class _Messages:
            def stream(self, **kw):
                # Snapshot: the caller mutates `messages` after the call returns.
                outer.requests.append({**kw, "messages": list(kw["messages"])})
                return _Stream(outer.responses.pop(0))

            def parse(self, **kw):
                outer.requests.append(kw)
                return outer.responses.pop(0)

        self.beta = SimpleNamespace(messages=_Messages())
