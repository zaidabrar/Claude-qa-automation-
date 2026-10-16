---
applyTo: "mobile-tests/src/test/java/**/steps/**/*.java"
---
# Step definitions

- Package `com.qa.mobile.steps`, one class per feature area (`LoginSteps`, `CheckoutSteps`). Take `TestContext` through the constructor (picocontainer). Never use static driver fields.
- Use Cucumber expressions (`{string}`, `{int}`), not regular expressions. Before adding a step, search all step classes for an equivalent pattern, because a duplicate fails as ambiguous.
- Steps are thin: create the page object from `ctx.driver()` and call one or two of its methods. No locators, waits, or `driver.find*` calls in step classes.
- Assert with AssertJ (`assertThat(...).as("what is checked")...`). Then steps verify outcomes. Given steps may only assert the precondition they establish (e.g. "the login screen is displayed"), so a setup failure is reported as such.
- Name methods after the step text in camelCase.
