"""MQTT publish helpers for the analytics container.

Same idiom as `_publish_json` / `publish_incident_tombstone` in
scripts/mqtt_poller.py (a standalone script, so copied rather than imported):
every publish funnels through here so a transient broker hiccup degrades one
publish and never kills the service.

Discrete publishes can carry an MQTT v5 `event_id` user property for the cloud
archive (2026-10-14, D-10/D-11): deterministic from message identity and
content, never from the publish-time clock, in the same format as the poller.
"""

from __future__ import annotations

import hashlib
import json
import logging

_logger = logging.getLogger("analytics.publish")

TOMBSTONE_WAIT_SECONDS = 5


def content_event_id(prefix: str, payload: object) -> str:
    """Stable event id `<prefix>-<16 hex of sha1>` computed from the payload alone.

    Copied from scripts/mqtt_poller.py (a standalone script, not importable);
    a parity test pins the two so cloud readers see one event_id format.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(blob).hexdigest()[:16]}"


def _event_properties(event_id: str | None):
    """MQTT v5 PUBLISH properties carrying `event_id`, or None when absent."""
    if event_id is None:
        return None
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties

    props = Properties(PacketTypes.PUBLISH)
    props.UserProperty = ("event_id", event_id)
    return props


def publish_retained_json(
    client, topic: str, payload: object, *, event_id: str | None = None
) -> None:
    """Publish `payload` as compact JSON, retained, QoS 1.

    Does not wait for the broker's acknowledgement: every retained output is
    republished on the next cycle, so a lost publish self-corrects.
    """
    try:
        client.publish(
            topic,
            json.dumps(payload, separators=(",", ":"), allow_nan=False),
            qos=1,
            retain=True,
            properties=_event_properties(event_id),
        )
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)
    except ValueError as exc:
        # allow_nan=False: a non-finite number would be invalid JSON for the browser.
        _logger.warning("Refusing to publish non-JSON-safe payload to %s: %s", topic, exc)


def publish_tombstone(client, topic: str, *, event_id: str | None = None) -> None:
    """Clear a retained topic with a zero-length retained payload (MQTT's clear semantic).

    Waits up to `TOMBSTONE_WAIT_SECONDS` for the publish so a tombstone is not
    lost on shutdown. Must not be called from the paho network thread (the
    acknowledgement is processed there); the service dispatches inbound
    messages to its own worker for exactly that reason.
    """
    try:
        info = client.publish(
            topic,
            payload=None,
            retain=True,
            qos=1,
            properties=_event_properties(event_id),
        )
        info.wait_for_publish(timeout=TOMBSTONE_WAIT_SECONDS)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)
