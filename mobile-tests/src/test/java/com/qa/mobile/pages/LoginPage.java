package com.qa.mobile.pages;

import io.appium.java_client.AppiumDriver;
import io.appium.java_client.pagefactory.AndroidFindBy;
import io.appium.java_client.pagefactory.iOSXCUITFindBy;
import org.openqa.selenium.WebElement;

/** Example page object. Replace the locators with your app's real ids. */
public class LoginPage extends BasePage {

  @AndroidFindBy(accessibility = "username-input")
  @iOSXCUITFindBy(accessibility = "username-input")
  private WebElement username;

  @AndroidFindBy(accessibility = "password-input")
  @iOSXCUITFindBy(accessibility = "password-input")
  private WebElement password;

  @AndroidFindBy(accessibility = "login-button")
  @iOSXCUITFindBy(accessibility = "login-button")
  private WebElement submit;

  @AndroidFindBy(accessibility = "login-error")
  @iOSXCUITFindBy(accessibility = "login-error")
  private WebElement error;

  public LoginPage(AppiumDriver driver) {
    super(driver);
  }

  public boolean isDisplayed() {
    return isVisible(submit, DEFAULT_TIMEOUT);
  }

  public void logIn(String user, String pass) {
    type(username, user);
    type(password, pass);
    tap(submit);
  }

  public String errorMessage() {
    return textOf(error);
  }
}
