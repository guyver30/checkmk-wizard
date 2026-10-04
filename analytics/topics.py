"""MQTT topic helpers for the analytics container (D-14).

`set_site_id`, `site_topic`, `relative_topic` and `is_publishable_device_id`
are copied from scripts/mqtt_poller.py: the poller is a standalone script
(not importable from here), so the copies are equality-tested against it in
tests/test_analytics_topics.py.
"""

from __future__ import annotations

import re

_SITE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")
_site_prefix: str | None = None
_TOPIC_UNSAFE_CHARS = ("+", "#", "/")

# Relative (site-less) topic the dashboard publishes triage commands on.
TRIAGE_CMD_TOPIC = "needs/triage/cmd"

# Need ids: f- (forecast), t- (trend) or s- (static) plus 12 hex chars.
NEED_ID_RE = re.compile(r"^[fts]-[0-9a-f]{12}\Z")


def set_site_id(site_id: str) -> None:
    """Set the `sites/<site_id>/` prefix every analytics topic is built under.

    Raises ValueError for anything that is not a valid Checkmk site id.
    """
    global _site_prefix
    if not _SITE_ID_RE.fullmatch(site_id):
        raise ValueError(
            f"CMK_SITE_ID {site_id!r} is not a valid Checkmk site id "
            "(letter first, then letters/digits/underscore, at most 16 characters)"
        )
    _site_prefix = f"sites/{site_id}/"


def site_topic(suffix: str) -> str:
    if _site_prefix is None:
        raise RuntimeError("set_site_id() was not called")
    return _site_prefix + suffix


def relative_topic(full: str) -> str | None:
    """Return `full` without this site's prefix, or None if it is not under it."""
    if _site_prefix is not None and full.startswith(_site_prefix):
        return full[len(_site_prefix) :]
    return None


def is_publishable_device_id(device_id: str) -> bool:
    """Reject any device id that would corrupt the MQTT topic hierarchy."""
    if not device_id or not device_id.strip():
        return False
    if any(ch in device_id for ch in _TOPIC_UNSAFE_CHARS):
        return False
    return not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in device_id)


def need_status_topic(need_id: str) -> str:
    return site_topic(f"lan/needs/{need_id}/status")


def forecast_topic(host: str) -> str:
    if not is_publishable_device_id(host):
        raise ValueError(f"host {host!r} is not safe to use in a topic")
    return site_topic(f"lan/forecasts/{host}")


def incident_narration_topic(incident_id: str) -> str:
    return site_topic(f"lan/incidents/{incident_id}/narration")
