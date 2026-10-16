"""Example page object. Replace locators with your app's real ids."""

from __future__ import annotations

from appium.webdriver.common.appiumby import AppiumBy

from .base_page import BasePage


class LoginPage(BasePage):
    USERNAME = {
        "android": (AppiumBy.ACCESSIBILITY_ID, "username-input"),
        "ios": (AppiumBy.ACCESSIBILITY_ID, "username-input"),
    }
    PASSWORD = {
        "android": (AppiumBy.ACCESSIBILITY_ID, "password-input"),
        "ios": (AppiumBy.ACCESSIBILITY_ID, "password-input"),
    }
    SUBMIT = {
        "android": (AppiumBy.ACCESSIBILITY_ID, "login-button"),
        "ios": (AppiumBy.ACCESSIBILITY_ID, "login-button"),
    }
    ERROR = {
        "android": (AppiumBy.ACCESSIBILITY_ID, "login-error"),
        "ios": (AppiumBy.ACCESSIBILITY_ID, "login-error"),
    }

    def is_loaded(self) -> bool:
        return self.is_visible(self.SUBMIT, timeout=self.timeout)

    def login(self, username: str, password: str) -> None:
        self.type(self.USERNAME, username)
        self.type(self.PASSWORD, password)
        self.hide_keyboard()
        self.tap(self.SUBMIT)

    def error_message(self) -> str:
        return self.text_of(self.ERROR)
