package com.qa.mobile.pages;

import io.appium.java_client.AppiumDriver;
import io.appium.java_client.pagefactory.AppiumFieldDecorator;
import java.time.Duration;
import org.openqa.selenium.TimeoutException;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.PageFactory;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.WebDriverWait;

/**
 * Base page object. Declare elements once for both platforms:
 *
 * <pre>
 * &#64;AndroidFindBy(accessibility = "login-button")
 * &#64;iOSXCUITFindBy(accessibility = "login-button")
 * private WebElement loginButton;
 * </pre>
 *
 * Prefer accessibility ids, then resource ids, then UiAutomator / iOS predicate strings. Never absolute XPath.
 */
public abstract class BasePage {

  protected static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(15);

  protected final AppiumDriver driver;
  protected final boolean ios;

  protected BasePage(AppiumDriver driver) {
    this.driver = driver;
    this.ios = "ios".equalsIgnoreCase(String.valueOf(driver.getCapabilities().getPlatformName()));
    PageFactory.initElements(new AppiumFieldDecorator(driver, Duration.ZERO), this);
  }

  protected WebDriverWait waitFor(Duration timeout) {
    return new WebDriverWait(driver, timeout);
  }

  protected WebElement visible(WebElement element) {
    return waitFor(DEFAULT_TIMEOUT).until(ExpectedConditions.visibilityOf(element));
  }

  protected boolean isVisible(WebElement element, Duration timeout) {
    try {
      waitFor(timeout).until(ExpectedConditions.visibilityOf(element));
      return true;
    } catch (TimeoutException e) {
      return false;
    }
  }

  protected void tap(WebElement element) {
    waitFor(DEFAULT_TIMEOUT).until(ExpectedConditions.elementToBeClickable(element)).click();
  }

  protected void type(WebElement element, String text) {
    WebElement field = visible(element);
    field.clear();
    field.sendKeys(text);
  }

  protected String textOf(WebElement element) {
    WebElement el = visible(element);
    String text = el.getText();
    return text != null && !text.isEmpty() ? text : el.getAttribute(ios ? "label" : "text");
  }
}
