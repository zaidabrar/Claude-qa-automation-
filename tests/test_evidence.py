from qa_harness.evidence import hint, locator_inventory
from qa_harness.models import Outcome, TestResult

from .fakes import ANDROID_SOURCE

IOS_SOURCE = """<AppiumAUT><XCUIElementTypeApplication name="Shop" visible="true">
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="checkout-button" label="Checkout" enabled="false"/>
  <XCUIElementTypeOther type="XCUIElementTypeOther"/>
</XCUIElementTypeApplication></AppiumAUT>"""


def r(message="", outcome=Outcome.failed, device="pixel", **artifacts) -> TestResult:
    return TestResult(node_id="f.feature:3", device=device, outcome=outcome, message=message, artifacts=artifacts)


def test_locator_inventory_android_and_ios():
    android = locator_inventory(ANDROID_SOURCE)
    assert 'EditText resource-id="com.app:id/user" content-desc="username-input" [clickable]' in android
    assert "View" not in android  # elements with nothing to locate are dropped
    ios = locator_inventory(IOS_SOURCE)
    assert 'XCUIElementTypeButton name="checkout-button" label="Checkout" [disabled]' in ios
    assert locator_inventory("<broken").startswith("(page source is not valid XML")


def test_hints(tmp_path):
    assert hint(r("UNDEFINED step: Given x"), [], []).startswith("test_defect:")
    assert hint(r("SessionNotCreatedException: no devices available"), [], []).startswith("environment")
    assert hint(r("NoSuchElementException: x", page_source="p"), [], []).startswith("test_defect (likely)")

    log = tmp_path / "device.log"
    log.write_text("I/Activity start\nE/AndroidRuntime: FATAL EXCEPTION: main\n")
    assert hint(r("Timeout", device_log=str(log)), [], []).startswith("product_bug")

    assert hint(r("expected x"), [], ["passed", "failed", "passed"]).startswith("unclear: this scenario flips")
    same = [r("expected x"), r(outcome=Outcome.passed, device="iphone")]
    assert "fails only on pixel" in hint(same[0], same, [])
