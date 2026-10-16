"""Data contracts passed between pipeline stages.

Every stage reads and writes these models so a run can be checkpointed to disk
and resumed, and so LLM outputs are schema-validated before anything acts on them.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- Jira


class Ticket(BaseModel):
    key: str
    summary: str
    description: str = ""
    issue_type: str = ""
    status: str = ""
    priority: str = ""
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    acceptance_criteria: str = ""
    comments: list[str] = Field(default_factory=list)
    linked_issues: list[str] = Field(default_factory=list)
    url: str = ""


# --------------------------------------------------------------------------- Planning


class Platform(str, Enum):
    android = "android"
    ios = "ios"


class CaseKind(str, Enum):
    happy_path = "happy_path"
    negative = "negative"
    edge = "edge"
    regression = "regression"
    accessibility = "accessibility"


class TestStep(BaseModel):
    __test__ = False  # not a pytest class

    action: str = Field(description="What the user does, e.g. 'Tap the Login button'.")
    expected: str = Field(description="Observable result that must be asserted.")


class TestCase(BaseModel):
    __test__ = False  # not a pytest class

    id: str = Field(description="Stable id like TC-01.")
    title: str
    kind: CaseKind
    priority: int = Field(description="1 = must pass for release, 3 = nice to have.", ge=1, le=3)
    preconditions: list[str]
    steps: list[TestStep]
    platforms: list[Platform]
    traces_to: list[str] = Field(description="Acceptance criteria this case verifies, quoted or numbered.")
    automatable: bool = Field(description="False when the case needs hardware/human judgement Appium cannot drive.")
    automation_notes: str = Field(description="Why not automatable, or hints for the automation engineer.")


class TestPlan(BaseModel):
    __test__ = False  # not a pytest class

    ticket_key: str
    feature_summary: str
    risks: list[str] = Field(description="What is most likely to break and why.")
    out_of_scope: list[str]
    ambiguities: list[str] = Field(
        description="Questions the ticket leaves unanswered. Assumptions made are stated here."
    )
    test_cases: list[TestCase]


# --------------------------------------------------------------------------- Generation


class GeneratedFile(BaseModel):
    path: str
    purpose: str


class GenerationResult(BaseModel):
    files: list[GeneratedFile]
    test_node_ids: list[str] = Field(description="pytest node ids for the new tests.")
    summary: str


# --------------------------------------------------------------------------- Execution


class Outcome(str, Enum):
    passed = "passed"
    failed = "failed"
    error = "error"
    skipped = "skipped"


class TestResult(BaseModel):
    __test__ = False  # not a pytest class

    node_id: str
    device: str
    outcome: Outcome
    duration_s: float = 0.0
    message: str = ""
    traceback: str = ""
    sauce_job_id: str | None = None
    sauce_url: str | None = None
    artifacts: dict[str, str] = Field(
        default_factory=dict, description="name -> local path (screenshot, page_source, logcat...)."
    )


class RunSummary(BaseModel):
    attempt: int
    results: list[TestResult]

    @property
    def failures(self) -> list[TestResult]:
        return [r for r in self.results if r.outcome in (Outcome.failed, Outcome.error)]

    @property
    def passed(self) -> bool:
        return bool(self.results) and not self.failures

    def counts(self) -> dict[str, int]:
        out = {o.value: 0 for o in Outcome}
        for r in self.results:
            out[r.outcome.value] += 1
        return out


# --------------------------------------------------------------------------- Triage


class FailureCategory(str, Enum):
    test_defect = "test_defect"  # wrong locator, missing wait, bad assertion -> fix the test
    product_bug = "product_bug"  # app violates acceptance criteria -> file a bug
    environment = "environment"  # Sauce/device/network/app-install flake -> retry
    needs_human = "needs_human"  # ambiguous requirement or cannot decide


class FailureVerdict(BaseModel):
    node_id: str
    device: str
    category: FailureCategory
    confidence: float = Field(ge=0.0, le=1.0)
    root_cause: str
    evidence: list[str] = Field(description="Concrete lines from logs/page source that support the verdict.")
    suggested_fix: str = Field(description="For test_defect: the code change. Otherwise the next action.")


class TriageReport(BaseModel):
    verdicts: list[FailureVerdict]
    summary: str


class BugReport(BaseModel):
    title: str
    severity: str = Field(description="Blocker, Critical, Major, Minor or Trivial.")
    environment: str
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    evidence: list[str]
    violated_criteria: list[str]
