"""Contract test: harness -> Maven/Surefire/TestNG/Cucumber -> QaResultsPlugin, on the real mobile-tests project.

No device is used: the scenarios' steps never touch the driver, which the suite only starts on demand.
Skipped when Maven/JDK are not installed.
"""

import shutil

import pytest

from qa_harness.config import DeviceConfig, Secrets, Settings
from qa_harness.framework import CucumberMaven
from qa_harness.models import Outcome
from qa_harness.stages.executor import SauceExecutor

pytestmark = pytest.mark.skipif(not (shutil.which("mvn") and shutil.which("java")), reason="needs Maven + JDK")

FEATURE = "src/test/resources/features/app_1/contract.feature"
FEATURE_TEXT = """@APP-1
Feature: Contract

  Scenario: passes
    Given a step that passes

  Scenario: fails
    Given a step that fails

  @ios
  Scenario: ios only
    Given a step that passes
"""
STEPS = """package com.qa.mobile.steps;

import io.cucumber.java.en.Given;

public class ContractSteps {
  @Given("a step that passes")
  public void passes() {}

  @Given("a step that fails")
  public void fails() {
    throw new AssertionError("banner not found");
  }
}
"""


@pytest.fixture
def project(sandbox_repo):
    root = sandbox_repo / "mobile-tests"
    (root / FEATURE).parent.mkdir(parents=True)
    (root / FEATURE).write_text(FEATURE_TEXT)
    (root / "src/test/java/com/qa/mobile/steps/ContractSteps.java").write_text(STEPS)
    return sandbox_repo


def test_discover_and_run_on_two_devices_concurrently(project):
    settings = Settings()
    settings.project.repo_root = project
    settings.sauce.devices = [
        DeviceConfig(name="pixel", platform="android", device_name="Pixel"),
        DeviceConfig(name="galaxy", platform="android", device_name="Galaxy"),
    ]
    framework = CucumberMaven(settings.tests_root, project)

    found = framework.discover([FEATURE])
    assert found.compiled, found.output
    assert found.ids == [f"{FEATURE}:4", f"{FEATURE}:7", f"{FEATURE}:11"]
    assert found.problems == {}

    ex = SauceExecutor(settings, Secrets(), None, framework, project / ".qa_runs" / "a")
    ids = [*found.ids, f"{FEATURE}:99"]  # a scenario that does not exist must not vanish
    summary = ex.run({"pixel": ids, "galaxy": ids}, attempt=1, build="b")

    for device in ("pixel", "galaxy"):
        got = {r.node_id: r for r in summary.results if r.device == device}
        assert got[f"{FEATURE}:4"].outcome == Outcome.passed
        assert got[f"{FEATURE}:4"].name == "passes"
        failed = got[f"{FEATURE}:7"]
        assert failed.outcome == Outcome.failed
        assert "Given a step that fails" in failed.message and "banner not found" in failed.message
        assert "ContractSteps.fails" in failed.traceback
        assert got[f"{FEATURE}:11"].outcome == Outcome.skipped  # @ios on an Android device
        assert got[f"{FEATURE}:99"].outcome == Outcome.error


def test_discovery_reports_undefined_steps(project):
    undefined = "\n  Scenario: undefined\n    Given nobody wrote me\n"
    (project / "mobile-tests" / FEATURE).write_text(FEATURE_TEXT + undefined)
    found = CucumberMaven(project / "mobile-tests", project).discover([FEATURE])
    assert found.problems == {f"{FEATURE}:14": "UNDEFINED step: Given nobody wrote me (line 15)"}


def test_compile_error_becomes_error_results(project):
    (project / "mobile-tests/src/test/java/com/qa/mobile/steps/Broken.java").write_text("class Broken { oops }")
    settings = Settings()
    settings.project.repo_root = project
    settings.sauce.devices = [DeviceConfig(name="pixel", platform="android", device_name="Pixel")]
    framework = CucumberMaven(settings.tests_root, project)
    assert framework.discover([FEATURE]).compiled is False
    summary = SauceExecutor(settings, Secrets(), None, framework, project / ".qa_runs" / "a").run(
        {"pixel": [f"{FEATURE}:4"]}, attempt=1, build="b"
    )
    assert [r.outcome for r in summary.results] == [Outcome.error]
    assert "Broken.java" in summary.results[0].traceback


def test_pipeline_discovers_generated_feature_with_real_maven(sandbox_repo):
    """Generate stage -> real Maven compile + Cucumber dry run -> scenario ids handed to execution."""
    from qa_harness.config import AutonomyMode
    from qa_harness.models import GeneratedFile, GenerationResult, TestPlan, Ticket
    from qa_harness.pipeline import Deps, Pipeline, new_state
    from qa_harness.state import Guard, RunStore

    from .fakes import ScriptedExecutor, ScriptedLLM, make_plan

    feature = "mobile-tests/src/test/resources/features/app_1/login_errors.feature"

    def generate(tools):
        out, err = tools.execute(
            "write_file",
            {
                "path": feature,
                "content": "@APP-1\nFeature: Login errors\n\n  @TC-01 @P1\n  Scenario: Wrong password shows error\n"
                "    Given the login screen is displayed\n"
                '    When I log in as "u" with password "bad"\n'
                '    Then I see a login error containing "invalid"\n',
            },
        )
        assert not err, out
        out, err = tools.execute("cucumber_dry_run", {"features": [feature]})
        assert "0 with problems" in out, out
        return GenerationResult(files=[GeneratedFile(path=feature, purpose="f")], test_node_ids=[], summary="s")

    settings = Settings()
    settings.project.repo_root = sandbox_repo
    settings.sauce.devices = [DeviceConfig(name="pixel", platform="android", device_name="Pixel")]
    settings.autonomy.mode = AutonomyMode.dry_run
    llm = ScriptedLLM().queue(TestPlan, make_plan())
    llm.agent_queue.append(generate)
    executor = ScriptedExecutor(settings.sauce.devices, [{}])
    deps = Deps(
        settings=settings,
        secrets=Secrets(),
        llm=llm,
        framework=CucumberMaven(settings.tests_root, sandbox_repo),
        executor=executor,
        load_ticket=lambda k: Ticket(key=k, summary="Login"),
    )
    state = new_state("APP-1")
    store = RunStore(settings.runs_root, state.run_id)
    result = Pipeline(deps, store, state, Guard(AutonomyMode.dry_run, store)).run()

    assert result.status == "passed"
    assert executor.calls == [{"pixel": ["src/test/resources/features/app_1/login_errors.feature:5"]}]
