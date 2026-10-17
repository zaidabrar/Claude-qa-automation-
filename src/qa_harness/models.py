"""Data contracts shared by the tools, the executor, and reports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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


class Outcome(str, Enum):
    passed = "passed"
    failed = "failed"
    error = "error"
    skipped = "skipped"


class TestResult(BaseModel):
    __test__ = False  # not a pytest class

    node_id: str = Field(description="Scenario id: <feature path relative to the test project>:<line>.")
    name: str = ""
    tags: list[str] = Field(default_factory=list)
    device: str
    outcome: Outcome
    duration_s: float = 0.0
    message: str = ""
    traceback: str = ""
    sauce_job_id: str | None = None
    sauce_url: str | None = None
    artifacts: dict[str, str] = Field(
        default_factory=dict, description="name -> local path (screenshot, page_source, device_log...)."
    )


class RunSummary(BaseModel):
    attempt: int
    results: list[TestResult]

    @property
    def failures(self) -> list[TestResult]:
        return [r for r in self.results if r.outcome in (Outcome.failed, Outcome.error)]

    def counts(self) -> dict[str, int]:
        out = {o.value: 0 for o in Outcome}
        for r in self.results:
            out[r.outcome.value] += 1
        return out


class BugReport(BaseModel):
    """What the agent supplies when it files a product bug. Evidence links are added by the tool."""

    title: str
    severity: str = Field(description="Blocker, Critical, Major, Minor or Trivial.")
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    violated_criteria: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Concrete lines from page source / logs.")
