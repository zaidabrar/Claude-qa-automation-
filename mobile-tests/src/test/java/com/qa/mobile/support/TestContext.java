package com.qa.mobile.support;

import io.appium.java_client.AppiumDriver;
import io.cucumber.java.Scenario;

/**
 * Per-scenario state shared between hooks and step classes (injected by cucumber-picocontainer).
 *
 * <p>The Appium session starts lazily on first use, so scenarios that never touch the UI cost no device time.
 */
public class TestContext {

  private Scenario scenario;
  private AppiumDriver driver;

  public void setScenario(Scenario scenario) {
    this.scenario = scenario;
  }

  public Scenario scenario() {
    return scenario;
  }

  public AppiumDriver driver() {
    if (driver == null) {
      driver = DriverFactory.create(DeviceConfig.current(), scenario.getName());
      ScenarioEvidence.setJobId(scenario.getId(), driver.getSessionId().toString());
    }
    return driver;
  }

  public boolean hasDriver() {
    return driver != null;
  }

  public void quit() {
    if (driver != null) {
      try {
        driver.quit();
      } finally {
        driver = null;
      }
    }
  }
}
