"""Appium session management for Sauce Labs (or a local Appium server).

The harness runs this suite once per device, describing the device through
environment variables. Running it by hand works the same way:

    QA_DEVICE='{"name":"pixel","platform":"android","device_name":"Google Pixel.*"}' \
    SAUCE_USERNAME=... SAUCE_ACCESS_KEY=... QA_APP_ANDROID=storage:filename=app.apk \
    pytest mobile_tests

On failure, a screenshot and the page source are saved for AI triage, and every
test result is written to ``$QA_RESULTS_FILE`` (JSON) with its Sauce job id.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

try:
    from appium import webdriver
    from appium.options.common import AppiumOptions
except ImportError:  # collection still works without Appium installed (e.g. lint/collect in CI)
    webdriver = None
    AppiumOptions = None

DEVICE = json.loads(os.environ.get("QA_DEVICE", "{}") or "{}")
PLATFORM = (DEVICE.get("platform") or os.environ.get("QA_PLATFORM", "android")).lower()
ARTIFACTS = Path(os.environ.get("QA_ARTIFACTS_DIR", ".qa_artifacts"))
RESULTS_FILE = os.environ.get("QA_RESULTS_FILE")
_results: list[dict] = []


def pytest_configure(config):
    config.addinivalue_line("markers", "platform(name): run only on 'android' or 'ios' devices")
    config.addinivalue_line("markers", "ticket(key): Jira ticket this test verifies")
    config.addinivalue_line("markers", "case(id): test-plan case id, e.g. TC-03")
    config.addinivalue_line("markers", "priority(n): 1 = release blocking")
    config.addinivalue_line("markers", "example: reference test, excluded from harness runs")


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = item.get_closest_marker("platform")
        if marker and PLATFORM not in [a.lower() for a in marker.args]:
            item.add_marker(pytest.mark.skip(reason=f"not applicable to {PLATFORM}"))


def _capabilities() -> dict:
    app = os.environ.get("QA_APP_IOS" if PLATFORM == "ios" else "QA_APP_ANDROID")
    caps = {
        "platformName": "iOS" if PLATFORM == "ios" else "Android",
        "appium:automationName": DEVICE.get("automation_name") or ("XCUITest" if PLATFORM == "ios" else "UiAutomator2"),
        "appium:deviceName": DEVICE.get("device_name", "Android GoogleAPI Emulator"),
        "appium:newCommandTimeout": 120,
        "appium:autoGrantPermissions": True,
    }
    if DEVICE.get("platform_version"):
        caps["appium:platformVersion"] = DEVICE["platform_version"]
    if app:
        caps["appium:app"] = app
    caps.update(DEVICE.get("extra_capabilities", {}))
    return caps


def _remote_url() -> tuple[str, dict]:
    if os.environ.get("APPIUM_URL"):  # local Appium server for debugging
        return os.environ["APPIUM_URL"], {}
    region = os.environ.get("SAUCE_REGION", "us-west-1")
    sauce = {
        "username": os.environ["SAUCE_USERNAME"],
        "accessKey": os.environ["SAUCE_ACCESS_KEY"],
        "appiumVersion": os.environ.get("SAUCE_APPIUM_VERSION", "latest"),
        "build": os.environ.get("QA_BUILD", f"local-{int(time.time())}"),
    }
    if os.environ.get("SAUCE_TUNNEL_NAME"):
        sauce["tunnelName"] = os.environ["SAUCE_TUNNEL_NAME"]
    return f"https://ondemand.{region}.saucelabs.com:443/wd/hub", sauce


@pytest.fixture
def driver(request):
    if webdriver is None:
        pytest.skip("Appium-Python-Client is not installed")
    url, sauce = _remote_url()
    caps = _capabilities()
    if sauce:
        caps["sauce:options"] = {**sauce, "name": request.node.nodeid}
    options = AppiumOptions()
    options.load_capabilities(caps)
    drv = webdriver.Remote(url, options=options)
    drv.implicitly_wait(0)  # page objects use explicit waits only
    request.node._qa_driver = drv
    yield drv
    report = getattr(request.node, "_qa_call_report", None)
    passed = bool(report and report.passed)
    if sauce:
        try:
            drv.execute_script(f"sauce:job-result={'passed' if passed else 'failed'}")
        except Exception:
            pass
    drv.quit()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    drv = getattr(item, "_qa_driver", None)

    if report.when == "call":
        item._qa_call_report = report

    if report.failed and drv is not None and report.when in ("setup", "call"):
        safe = "".join(c if c.isalnum() else "_" for c in item.nodeid)[-120:]
        dest = ARTIFACTS / DEVICE.get("name", PLATFORM) / safe
        dest.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        try:
            drv.save_screenshot(str(dest / "screenshot.png"))
            artifacts["screenshot"] = str(dest / "screenshot.png")
        except Exception:
            pass
        try:
            (dest / "page_source.xml").write_text(drv.page_source)
            artifacts["page_source"] = str(dest / "page_source.xml")
        except Exception:
            pass
        item._qa_artifacts = artifacts

    is_final = report.when == "call" or (report.when == "setup" and not report.passed)
    if is_final:
        outcome_name = "skipped" if report.skipped else ("passed" if report.passed else "failed")
        if report.when == "setup" and report.failed:
            outcome_name = "error"
        _results.append(
            {
                "node_id": item.nodeid,
                "device": DEVICE.get("name", PLATFORM),
                "outcome": outcome_name,
                "duration_s": round(report.duration, 2),
                "message": str(getattr(call.excinfo, "value", ""))[:2000] if call.excinfo else "",
                "traceback": report.longreprtext[-6000:] if report.failed else "",
                "sauce_job_id": getattr(drv, "session_id", None) if drv else None,
                "artifacts": getattr(item, "_qa_artifacts", {}),
            }
        )


def pytest_sessionfinish(session, exitstatus):
    if RESULTS_FILE:
        Path(RESULTS_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(RESULTS_FILE).write_text(json.dumps(_results, indent=2))
