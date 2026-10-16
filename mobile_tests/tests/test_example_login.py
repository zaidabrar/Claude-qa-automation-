"""Reference test showing the conventions generated tests follow."""

import pytest

from mobile_tests.pages.login_page import LoginPage


@pytest.mark.example
@pytest.mark.ticket("EXAMPLE-1")
@pytest.mark.case("TC-01")
@pytest.mark.priority(1)
def test_invalid_password_shows_error(driver):
    login = LoginPage(driver)
    assert login.is_loaded(), "Login screen did not appear"

    login.login("standard_user", "wrong-password")

    assert "invalid" in login.error_message().lower()
