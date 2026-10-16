package com.qa.mobile.support;

import io.appium.java_client.AppiumDriver;
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.ios.IOSDriver;
import java.net.MalformedURLException;
import java.net.URI;
import java.net.URL;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import org.openqa.selenium.MutableCapabilities;

/** Builds Appium sessions on Sauce Labs, or on a local Appium server when {@code APPIUM_URL} is set. */
public final class DriverFactory {

  private DriverFactory() {}

  public static boolean onSauce() {
    return System.getenv("APPIUM_URL") == null;
  }

  public static AppiumDriver create(DeviceConfig device, String testName) {
    MutableCapabilities caps = new MutableCapabilities();
    caps.setCapability("platformName", device.isIos() ? "iOS" : "Android");
    caps.setCapability("appium:automationName", device.automationName);
    caps.setCapability("appium:deviceName", device.deviceName);
    caps.setCapability("appium:newCommandTimeout", 120);
    caps.setCapability("appium:autoGrantPermissions", true);
    if (!device.platformVersion.isEmpty()) {
      caps.setCapability("appium:platformVersion", device.platformVersion);
    }
    String app = System.getenv(device.isIos() ? "QA_APP_IOS" : "QA_APP_ANDROID");
    if (app != null && !app.isBlank()) {
      caps.setCapability("appium:app", app);
    }
    device.extraCapabilities.forEach(caps::setCapability);

    String url;
    if (onSauce()) {
      Map<String, Object> sauce = new HashMap<>();
      sauce.put("username", required("SAUCE_USERNAME"));
      sauce.put("accessKey", required("SAUCE_ACCESS_KEY"));
      sauce.put("appiumVersion", DeviceConfig.env("SAUCE_APPIUM_VERSION", "latest"));
      sauce.put("build", DeviceConfig.env("QA_BUILD", "local-" + System.currentTimeMillis()));
      sauce.put("name", testName);
      String tunnel = System.getenv("SAUCE_TUNNEL_NAME");
      if (tunnel != null && !tunnel.isBlank()) {
        sauce.put("tunnelName", tunnel);
      }
      caps.setCapability("sauce:options", sauce);
      url = "https://ondemand." + DeviceConfig.env("SAUCE_REGION", "us-west-1") + ".saucelabs.com:443/wd/hub";
    } else {
      url = System.getenv("APPIUM_URL");
    }

    URL remote = toUrl(url);
    AppiumDriver driver = device.isIos() ? new IOSDriver(remote, caps) : new AndroidDriver(remote, caps);
    driver.manage().timeouts().implicitlyWait(Duration.ZERO); // page objects use explicit waits only
    return driver;
  }

  private static URL toUrl(String url) {
    try {
      return URI.create(url).toURL();
    } catch (MalformedURLException e) {
      throw new IllegalArgumentException("Bad Appium URL: " + url, e);
    }
  }

  private static String required(String key) {
    String value = System.getenv(key);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException(key + " is not set");
    }
    return value;
  }
}
