"""Runs the real executor -> pytest -> mobile_tests/conftest.py contract, with a fake Appium driver."""

from qa_harness.config import DeviceConfig, Secrets, Settings
from qa_harness.models import Outcome
from qa_harness.stages.executor import SauceExecutor

SUITE = """import pytest


class FakeDriver:
    session_id = "sauce-job-123"

    def save_screenshot(self, path):
        open(path, "wb").write(b"\\x89PNG fake")

    @property
    def page_source(self):
        return "<hierarchy><node content-desc='login-button'/></hierarchy>"


@pytest.fixture
def fake_driver(request):
    request.node._qa_driver = FakeDriver()
    return request.node._qa_driver


def test_passes(fake_driver):
    assert True


def test_fails(fake_driver):
    assert False, "banner not found"


@pytest.mark.platform("ios")
def test_ios_only(fake_driver):
    assert True
"""


def test_executor_collects_results_and_evidence(sandbox_repo):
    (sandbox_repo / "mobile_tests" / "tests" / "test_contract.py").write_text(SUITE)
    settings = Settings()
    settings.project.repo_root = sandbox_repo
    settings.sauce.devices = [DeviceConfig(name="pixel", platform="android", device_name="Pixel")]
    ex = SauceExecutor(settings, Secrets(), sauce=None, artifacts_root=sandbox_repo / ".qa_runs" / "a")

    base = "mobile_tests/tests/test_contract.py::"
    nodes = [base + n for n in ("test_passes", "test_fails", "test_ios_only")]
    summary = ex.run({"pixel": nodes}, attempt=1, build="b")

    by_name = {r.node_id.split("::")[-1]: r for r in summary.results}
    assert by_name["test_passes"].outcome == Outcome.passed
    assert by_name["test_ios_only"].outcome == Outcome.skipped  # platform marker honoured
    failed = by_name["test_fails"]
    assert failed.outcome == Outcome.failed and "banner not found" in failed.message
    assert failed.sauce_job_id == "sauce-job-123"
    assert failed.sauce_url == "https://app.saucelabs.com/tests/sauce-job-123"
    assert "login-button" in open(failed.artifacts["page_source"]).read()
    assert open(failed.artifacts["screenshot"], "rb").read().startswith(b"\x89PNG")
    assert summary.failures == [failed]


def test_executor_reports_suite_crash_as_errors(sandbox_repo):
    (sandbox_repo / "mobile_tests" / "tests" / "test_broken.py").write_text("import nonexistent_module\n")
    settings = Settings()
    settings.project.repo_root = sandbox_repo
    settings.sauce.devices = [DeviceConfig(name="pixel", platform="android", device_name="Pixel")]
    ex = SauceExecutor(settings, Secrets(), sauce=None, artifacts_root=sandbox_repo / ".qa_runs" / "a")
    node = "mobile_tests/tests/test_broken.py::test_x"
    summary = ex.run({"pixel": [node]}, attempt=1, build="b")
    assert [r.outcome for r in summary.results] == [Outcome.error]
    assert "nonexistent_module" in summary.results[0].traceback
