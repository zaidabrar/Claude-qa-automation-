package com.qa.mobile.hooks;

import com.qa.mobile.support.DeviceConfig;
import com.qa.mobile.support.DriverFactory;
import com.qa.mobile.support.ScenarioEvidence;
import com.qa.mobile.support.TestContext;
import io.cucumber.java.After;
import io.cucumber.java.Before;
import io.cucumber.java.Scenario;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.openqa.selenium.OutputType;
import org.testng.SkipException;

/** Scenario lifecycle: platform filtering, failure evidence for AI triage, Sauce job status, teardown. */
public class Hooks {

  private final TestContext ctx;

  public Hooks(TestContext ctx) {
    this.ctx = ctx;
  }

  @Before(order = 0)
  public void start(Scenario scenario) {
    ctx.setScenario(scenario);
    String platform = DeviceConfig.current().platform;
    boolean android = scenario.getSourceTagNames().contains("@android");
    boolean ios = scenario.getSourceTagNames().contains("@ios");
    if ((android || ios) && !scenario.getSourceTagNames().contains("@" + platform)) {
      throw new SkipException("Not applicable to " + platform);
    }
  }

  @After(order = 0)
  public void finish(Scenario scenario) {
    if (!ctx.hasDriver()) {
      return;
    }
    try {
      if (scenario.isFailed()) {
        captureEvidence(scenario);
      }
      if (DriverFactory.onSauce()) {
        ctx.driver().executeScript("sauce:job-result=" + (scenario.isFailed() ? "failed" : "passed"));
      }
    } catch (RuntimeException e) {
      scenario.log("Teardown problem: " + e);
    } finally {
      ctx.quit();
    }
  }

  private void captureEvidence(Scenario scenario) {
    Path dir = Paths.get(DeviceConfig.env("QA_ARTIFACTS_DIR", "target/qa-artifacts"))
        .resolve(DeviceConfig.current().name)
        .resolve(safe(scenario.getUri() + "_" + scenario.getLine()));
    try {
      Files.createDirectories(dir);
      byte[] png = ctx.driver().getScreenshotAs(OutputType.BYTES);
      Path shot = dir.resolve("screenshot.png");
      Files.write(shot, png);
      scenario.attach(png, "image/png", "screenshot");
      ScenarioEvidence.addArtifact(scenario.getId(), "screenshot", shot.toAbsolutePath().toString());

      Path source = dir.resolve("page_source.xml");
      Files.writeString(source, ctx.driver().getPageSource(), StandardCharsets.UTF_8);
      ScenarioEvidence.addArtifact(scenario.getId(), "page_source", source.toAbsolutePath().toString());
    } catch (IOException | RuntimeException e) {
      scenario.log("Could not capture evidence: " + e);
    }
  }

  private static String safe(String text) {
    String s = text.replaceAll("[^A-Za-z0-9]+", "_");
    return s.length() <= 120 ? s : s.substring(s.length() - 120);
  }
}
