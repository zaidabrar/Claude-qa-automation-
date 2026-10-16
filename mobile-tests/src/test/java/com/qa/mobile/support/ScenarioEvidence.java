package com.qa.mobile.support;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Hands Sauce job ids and evidence file paths from hooks to {@link QaResultsPlugin}, keyed by scenario id. */
public final class ScenarioEvidence {

  private static final Map<String, String> JOB_IDS = new ConcurrentHashMap<>();
  private static final Map<String, Map<String, String>> ARTIFACTS = new ConcurrentHashMap<>();

  private ScenarioEvidence() {}

  public static void setJobId(String scenarioId, String jobId) {
    JOB_IDS.put(scenarioId, jobId);
  }

  public static void addArtifact(String scenarioId, String name, String path) {
    ARTIFACTS.computeIfAbsent(scenarioId, k -> new ConcurrentHashMap<>()).put(name, path);
  }

  static String jobId(String scenarioId) {
    return JOB_IDS.get(scenarioId);
  }

  static Map<String, String> artifacts(String scenarioId) {
    return ARTIFACTS.getOrDefault(scenarioId, Map.of());
  }
}
