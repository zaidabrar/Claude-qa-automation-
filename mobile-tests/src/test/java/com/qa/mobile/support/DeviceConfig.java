package com.qa.mobile.support;

import java.util.Collections;
import java.util.Map;
import org.openqa.selenium.json.Json;

/**
 * The device this JVM targets, described by the harness in {@code QA_DEVICE} (JSON).
 *
 * <p>Running by hand: {@code QA_DEVICE='{"name":"pixel","platform":"android","device_name":"Google Pixel.*"}'}
 */
public final class DeviceConfig {

  private static DeviceConfig current;

  public final String name;
  public final String platform;
  public final String deviceName;
  public final String platformVersion;
  public final String automationName;
  public final Map<String, Object> extraCapabilities;

  @SuppressWarnings("unchecked")
  private DeviceConfig(Map<String, Object> raw) {
    this.platform = str(raw.get("platform"), env("QA_PLATFORM", "android")).toLowerCase();
    this.name = str(raw.get("name"), platform);
    this.deviceName = str(raw.get("device_name"), isIos() ? "iPhone Simulator" : "Android GoogleAPI Emulator");
    this.platformVersion = str(raw.get("platform_version"), "");
    this.automationName = str(raw.get("automation_name"), isIos() ? "XCUITest" : "UiAutomator2");
    Object extra = raw.get("extra_capabilities");
    this.extraCapabilities = extra instanceof Map ? (Map<String, Object>) extra : Collections.emptyMap();
  }

  public static synchronized DeviceConfig current() {
    if (current == null) {
      String json = env("QA_DEVICE", "");
      Map<String, Object> raw = json.isBlank() ? Map.of() : new Json().toType(json, Json.MAP_TYPE);
      current = new DeviceConfig(raw);
    }
    return current;
  }

  public boolean isIos() {
    return "ios".equals(platform);
  }

  public static String env(String key, String fallback) {
    String value = System.getenv(key);
    return value == null || value.isBlank() ? fallback : value;
  }

  private static String str(Object value, String fallback) {
    return value == null || value.toString().isBlank() ? fallback : value.toString();
  }
}
