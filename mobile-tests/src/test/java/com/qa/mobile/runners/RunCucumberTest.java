package com.qa.mobile.runners;

import io.cucumber.testng.AbstractTestNGCucumberTests;
import io.cucumber.testng.CucumberOptions;
import org.testng.annotations.DataProvider;

/**
 * TestNG entry point. The harness narrows the run with system properties, which override these options:
 * {@code -Dcucumber.features=path/a.feature:12,path/b.feature:7} and {@code -Dcucumber.filter.tags=...}.
 */
@CucumberOptions(
    features = "src/test/resources/features",
    glue = "com.qa.mobile",
    tags = "not @example",
    plugin = {"pretty", "summary", "com.qa.mobile.support.QaResultsPlugin"})
public class RunCucumberTest extends AbstractTestNGCucumberTests {

  /** One device session at a time per JVM; the harness parallelises across devices instead. */
  @Override
  @DataProvider(parallel = false)
  public Object[][] scenarios() {
    return super.scenarios();
  }
}
