"""Base page object: platform-aware locators and explicit waits.

Locators are declared per platform so one page object serves Android and iOS:

    LOGIN_BUTTON = {"android": (AppiumBy.ID, "com.example:id/login"),
                    "ios": (AppiumBy.ACCESSIBILITY_ID, "Login")}

Prefer accessibility ids, then resource ids, then -ios predicate strings /
UiAutomator selectors. Avoid absolute XPath: it is the main source of flaky tests.
"""

from __future__ import annotations

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

Locator = tuple[str, str]
PlatformLocator = Locator | dict[str, Locator]

DEFAULT_TIMEOUT = 15


class BasePage:
    def __init__(self, driver, timeout: int = DEFAULT_TIMEOUT):
        self.driver = driver
        self.timeout = timeout
        self.platform = str(driver.capabilities.get("platformName", "android")).lower()

    # ------------------------------------------------------------------ locators

    def _loc(self, locator: PlatformLocator) -> Locator:
        if isinstance(locator, dict):
            if self.platform not in locator:
                raise KeyError(f"No {self.platform} locator defined: {locator}")
            return locator[self.platform]
        return locator

    def _wait(self, timeout: int | None = None) -> WebDriverWait:
        return WebDriverWait(self.driver, timeout or self.timeout)

    # ------------------------------------------------------------------ queries

    def find(self, locator: PlatformLocator, timeout: int | None = None):
        return self._wait(timeout).until(EC.presence_of_element_located(self._loc(locator)))

    def find_visible(self, locator: PlatformLocator, timeout: int | None = None):
        return self._wait(timeout).until(EC.visibility_of_element_located(self._loc(locator)))

    def is_visible(self, locator: PlatformLocator, timeout: int = 3) -> bool:
        try:
            self.find_visible(locator, timeout)
            return True
        except TimeoutException:
            return False

    def wait_gone(self, locator: PlatformLocator, timeout: int | None = None) -> None:
        self._wait(timeout).until(EC.invisibility_of_element_located(self._loc(locator)))

    def text_of(self, locator: PlatformLocator) -> str:
        el = self.find_visible(locator)
        return el.text or el.get_attribute("label" if self.platform == "ios" else "text") or ""

    # ------------------------------------------------------------------ actions

    def tap(self, locator: PlatformLocator, timeout: int | None = None) -> None:
        self._wait(timeout).until(EC.element_to_be_clickable(self._loc(locator))).click()

    def type(self, locator: PlatformLocator, text: str, clear: bool = True) -> None:
        el = self.find_visible(locator)
        if clear:
            el.clear()
        el.send_keys(text)

    def hide_keyboard(self) -> None:
        try:
            self.driver.hide_keyboard()
        except Exception:
            pass

    def scroll_to_text(self, text: str) -> None:
        if self.platform == "android":
            self.driver.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().text("{text}"))',
            )
        else:
            self.driver.execute_script("mobile: scroll", {"predicateString": f"label == '{text}'"})

    def back(self) -> None:
        self.driver.back()
