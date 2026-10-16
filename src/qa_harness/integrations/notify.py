"""Optional Slack (incoming webhook) notifications."""

from __future__ import annotations

import logging

import httpx2 as httpx

log = logging.getLogger(__name__)


def slack(webhook: str | None, text: str) -> None:
    if not webhook:
        return
    try:
        httpx.post(webhook, json={"text": text}, timeout=10.0)
    except httpx.HTTPError as exc:  # notifications must never fail a run
        log.warning("Slack notification failed: %s", exc)
