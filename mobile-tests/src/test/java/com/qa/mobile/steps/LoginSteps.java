package com.qa.mobile.steps;

import static org.assertj.core.api.Assertions.assertThat;

import com.qa.mobile.pages.LoginPage;
import com.qa.mobile.support.TestContext;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;

/** Example step definitions showing the conventions generated steps follow. */
public class LoginSteps {

  private final TestContext ctx;

  public LoginSteps(TestContext ctx) {
    this.ctx = ctx;
  }

  private LoginPage loginPage() {
    return new LoginPage(ctx.driver());
  }

  @Given("the login screen is displayed")
  public void theLoginScreenIsDisplayed() {
    assertThat(loginPage().isDisplayed()).as("login screen visible").isTrue();
  }

  @When("I log in as {string} with password {string}")
  public void iLogInAs(String user, String password) {
    loginPage().logIn(user, password);
  }

  @Then("I see a login error containing {string}")
  public void iSeeALoginErrorContaining(String expected) {
    assertThat(loginPage().errorMessage()).containsIgnoringCase(expected);
  }
}
