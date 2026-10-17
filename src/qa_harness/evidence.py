"""Turns raw failure artifacts into compact evidence an agent can reason over.

* ``locator_inventory`` condenses an Appium page source (often 100k+ characters) into one line per
  element that has a usable locator, so Copilot can fix locators from attributes that really exist.
* ``log_excerpt`` keeps crash lines (with context) plus the log tail.
* ``hint`` is a deterministic first guess at the failure category. The agent makes the final call.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Outcome, TestResult

CRASH = re.compile(r"FATAL EXCEPTION|ANR in|has crashed|SIGABRT|SIGSEGV|Terminating app|EXC_BAD_ACCESS", re.I)

ENVIRONMENT = re.compile(
    r"SessionNotCreated|Could not start a new session|no devices? (?:available|found)|device .* unavailable|"
    r"UnreachableBrowser|Connection refused|ECONNRESET|tunnel|app (?:could not be )?install|"
    r"INSTALL_FAILED|failed to install|Sauce Labs.*(?:queue|concurrency)|timed out after \d+s",
    re.I,
)
TEST_DEFECT = re.compile(r"UNDEFINED step|AMBIGUOUS step|PENDING step|Compilation failed|Did not run", re.I)
LOCATOR = re.compile(r"NoSuchElement|TimeoutException|StaleElementReference|ElementNotInteractable", re.I)

# Attributes worth showing, per platform. Android: UiAutomator2, iOS: XCUITest.
ANDROID_ATTRS = ("resource-id", "content-desc", "text")
IOS_ATTRS = ("name", "label", "value")


def locator_inventory(xml_text: str, limit: int = 250) -> str:
    """One line per element that a locator could target: type, ids, text, visibility, bounds."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return f"(page source is not valid XML: {exc})"
    lines: list[str] = []
    for el in root.iter():
        attrs = el.attrib
        keys = ANDROID_ATTRS if "resource-id" in attrs or "content-desc" in attrs else IOS_ATTRS
        shown = {k: attrs[k] for k in keys if attrs.get(k)}
        if not shown:
            continue
        kind = (attrs.get("class") or attrs.get("type") or el.tag).rsplit(".", 1)[-1]
        flags = []
        if attrs.get("displayed", attrs.get("visible", "true")) == "false":
            flags.append("hidden")
        if attrs.get("enabled") == "false":
            flags.append("disabled")
        if attrs.get("clickable") == "true":
            flags.append("clickable")
        detail = " ".join(f'{k}="{v[:80]}"' for k, v in shown.items())
        lines.append(f"{kind} {detail}" + (f" [{', '.join(flags)}]" if flags else ""))
        if len(lines) >= limit:
            lines.append(f"... (truncated at {limit} elements)")
            break
    return "\n".join(lines) or "(no elements with locatable attributes)"


def log_excerpt(path: str | None, tail: int = 60) -> str:
    if not path or not Path(path).is_file():
        return ""
    lines = Path(path).read_text(errors="replace").splitlines()
    picked: list[str] = []
    for i, line in enumerate(lines):
        if CRASH.search(line):
            picked += lines[max(0, i - 3) : i + 25] + ["..."]
            if len(picked) > 200:
                break
    return "\n".join(picked[:200] + ["--- tail ---"] + lines[-tail:])


def has_crash(result: TestResult) -> bool:
    for name in ("device_log", "logcat"):
        path = result.artifacts.get(name)
        if path and Path(path).is_file() and CRASH.search(Path(path).read_text(errors="replace")):
            return True
    return False


def hint(result: TestResult, same_scenario: list[TestResult], history: list[str]) -> str:
    """Deterministic first guess: test_defect | product_bug | environment | unclear, with the reason."""
    text = f"{result.message}\n{result.traceback}"
    if TEST_DEFECT.search(text):
        return "test_defect: the scenario is not runnable as written (undefined/ambiguous step or compile error)"
    if has_crash(result):
        return "product_bug: the app crashed (see device log excerpt)"
    if ENVIRONMENT.search(text) and not result.artifacts.get("page_source"):
        return "environment: the session/device/app install failed before the app was exercised"
    failing_devices = {r.device for r in same_scenario if r.outcome in (Outcome.failed, Outcome.error)}
    all_devices = {r.device for r in same_scenario}
    flaky = len(history) >= 3 and len(set(history[-5:])) > 1
    if flaky:
        return "unclear: this scenario flips between pass and fail across runs (likely flaky); re-run before deciding"
    if LOCATOR.search(text):
        return (
            "test_defect (likely): element not found or not interactable; compare the locator with the inventory. "
            "If the element the ticket requires is genuinely absent, it is a product_bug"
        )
    if len(all_devices) > 1 and failing_devices != all_devices:
        return f"unclear: fails only on {', '.join(sorted(failing_devices))}; a platform-specific bug or device flake"
    return "unclear: an assertion failed; compare the expected value with the screenshot and page source"
