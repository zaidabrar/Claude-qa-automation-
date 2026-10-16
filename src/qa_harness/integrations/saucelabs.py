"""Sauce Labs REST client: app storage, job lookup, and evidence download.

Test sessions themselves are started by the Appium suite (see mobile_tests/conftest.py);
this client handles everything around them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2 as httpx

from ..config import DeviceConfig, SauceConfig


class SauceClient:
    def __init__(self, cfg: SauceConfig, username: str, access_key: str, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.username = username
        self.http = httpx.Client(
            base_url=f"https://api.{cfg.region}.saucelabs.com",
            auth=(username, access_key),
            timeout=httpx.Timeout(60.0, write=600.0),
            transport=transport,
        )

    @property
    def webdriver_url(self) -> str:
        return f"https://ondemand.{self.cfg.region}.saucelabs.com:443/wd/hub"

    @staticmethod
    def job_url(job_id: str) -> str:
        return f"https://app.saucelabs.com/tests/{job_id}"

    # ------------------------------------------------------------------ app storage

    def resolve_app(self, app: str | None) -> str | None:
        """Return an Appium ``app`` capability, uploading a local binary when given a path."""
        if not app:
            return None
        if app.startswith(("storage:", "http://", "https://")):
            return app
        path = Path(app)
        if not path.is_file():
            raise FileNotFoundError(f"App binary not found: {app}")
        return f"storage:{self.upload_app(path)}"

    def upload_app(self, path: Path) -> str:
        with path.open("rb") as fh:
            r = self.http.post("/v1/storage/upload", files={"payload": (path.name, fh)}, data={"name": path.name})
        r.raise_for_status()
        return r.json()["item"]["id"]

    # ------------------------------------------------------------------ jobs

    def get_job(self, job_id: str, real_device: bool) -> dict[str, Any]:
        path = f"/v1/rdc/jobs/{job_id}" if real_device else f"/rest/v1/{self.username}/jobs/{job_id}"
        r = self.http.get(path)
        r.raise_for_status()
        return r.json()

    def set_job_result(self, job_id: str, passed: bool, real_device: bool) -> None:
        path = f"/v1/rdc/jobs/{job_id}" if real_device else f"/rest/v1/{self.username}/jobs/{job_id}"
        self.http.put(path, json={"passed": passed})

    def download_evidence(self, job_id: str, real_device: bool, dest: Path) -> dict[str, str]:
        """Best-effort download of device/Appium logs for triage. Returns name -> local path."""
        dest.mkdir(parents=True, exist_ok=True)
        if real_device:
            candidates = {
                "device_log": f"/v1/rdc/jobs/{job_id}/deviceLogs",
                "appium_log": f"/v1/rdc/jobs/{job_id}/appiumLogs",
            }
        else:
            base = f"/rest/v1/{self.username}/jobs/{job_id}/assets"
            candidates = {
                "appium_log": f"{base}/appium-server.log",
                "logcat": f"{base}/logcat.log",
                "commands": f"{base}/log.json",
            }
        saved: dict[str, str] = {}
        for name, path in candidates.items():
            try:
                r = self.http.get(path)
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and r.content:
                out = dest / f"{name}.log"
                out.write_bytes(r.content[-2_000_000:])  # tail; logs can be huge
                saved[name] = str(out)
        return saved


def default_automation(device: DeviceConfig) -> str:
    if device.automation_name:
        return device.automation_name
    return "XCUITest" if device.platform.lower() == "ios" else "UiAutomator2"
