package com.qa.mobile.support;

import io.cucumber.plugin.ConcurrentEventListener;
import io.cucumber.plugin.event.EventPublisher;
import io.cucumber.plugin.event.PickleStepTestStep;
import io.cucumber.plugin.event.Result;
import io.cucumber.plugin.event.Status;
import io.cucumber.plugin.event.TestCase;
import io.cucumber.plugin.event.TestCaseFinished;
import io.cucumber.plugin.event.TestRunFinished;
import io.cucumber.plugin.event.TestStepFinished;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.openqa.selenium.json.Json;

/**
 * Writes one JSON record per scenario to {@code $QA_RESULTS_FILE} for the QA harness.
 *
 * <p>The scenario id is {@code <feature path relative to the project>:<line>}, which is also what
 * {@code -Dcucumber.features=...} accepts, so the harness can re-run exactly the scenarios that failed.
 */
public class QaResultsPlugin implements ConcurrentEventListener {

  private static final int MAX_TRACE = 6000;

  private final List<Map<String, Object>> results = Collections.synchronizedList(new ArrayList<>());
  private final Map<String, String> failedStep = new ConcurrentHashMap<>();

  @Override
  public void setEventPublisher(EventPublisher publisher) {
    publisher.registerHandlerFor(TestStepFinished.class, this::onStep);
    publisher.registerHandlerFor(TestCaseFinished.class, this::onCase);
    publisher.registerHandlerFor(TestRunFinished.class, e -> write());
  }

  private void onStep(TestStepFinished event) {
    Status status = event.getResult().getStatus();
    if (status == Status.PASSED || status == Status.SKIPPED || status == Status.UNUSED) {
      return;
    }
    if (event.getTestStep() instanceof PickleStepTestStep step) {
      String text = step.getStep().getKeyword() + step.getStep().getText() + " (line " + step.getStep().getLine() + ")";
      failedStep.putIfAbsent(event.getTestCase().getId().toString(), status + " step: " + text);
    }
  }

  private void onCase(TestCaseFinished event) {
    TestCase tc = event.getTestCase();
    Result result = event.getResult();
    String id = tc.getId().toString();

    Map<String, Object> r = new LinkedHashMap<>();
    r.put("node_id", relative(tc.getUri()) + ":" + tc.getLocation().getLine());
    r.put("name", tc.getName());
    r.put("device", DeviceConfig.current().name);
    r.put("outcome", outcome(result.getStatus()));
    r.put("duration_s", result.getDuration().toMillis() / 1000.0);
    String step = failedStep.getOrDefault(id, "");
    Throwable error = result.getError();
    r.put("message", (step + (error != null ? "\n" + error : "")).trim());
    r.put("traceback", error != null ? trace(error) : "");
    r.put("sauce_job_id", ScenarioEvidence.jobId(id));
    r.put("artifacts", ScenarioEvidence.artifacts(id));
    r.put("tags", tc.getTags());
    results.add(r);
  }

  private void write() {
    String file = System.getenv("QA_RESULTS_FILE");
    if (file == null || file.isBlank()) {
      return;
    }
    try {
      Path path = Paths.get(file);
      if (path.getParent() != null) {
        Files.createDirectories(path.getParent());
      }
      Files.writeString(path, new Json().toJson(results));
    } catch (IOException e) {
      throw new IllegalStateException("Could not write " + file, e);
    }
  }

  private static String outcome(Status status) {
    return switch (status) {
      case PASSED -> "passed";
      case SKIPPED -> "skipped";
      case FAILED -> "failed";
      default -> "error"; // UNDEFINED, PENDING, AMBIGUOUS, UNUSED: the scenario is not a valid test
    };
  }

  private static String relative(URI uri) {
    if (!"file".equals(uri.getScheme())) {
      return uri.toString();
    }
    Path cwd = Paths.get("").toAbsolutePath();
    return cwd.relativize(Paths.get(uri)).toString().replace('\\', '/');
  }

  private static String trace(Throwable error) {
    StringWriter out = new StringWriter();
    error.printStackTrace(new PrintWriter(out));
    String text = out.toString();
    return text.length() <= MAX_TRACE ? text : text.substring(0, MAX_TRACE);
  }
}
