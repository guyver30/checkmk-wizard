"""MQTT publish helpers for the analytics container.

Same idiom as `_publish_json` / `publish_incident_tombstone` in
scripts/mqtt_poller.py (a standalone script, so copied rather than imported):
every publish funnels through here so a transient broker hiccup degrades one
publish and never kills the service.
"""

from __future__ import annotations

import json
import logging

_logger = logging.getLogger("analytics.publish")

TOMBSTONE_WAIT_SECONDS = 5


def publish_retained_json(client, topic: str, payload: object) -> None:
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
        )
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)
    except ValueError as exc:
        # allow_nan=False: a non-finite number would be invalid JSON for the browser.
        _logger.warning("Refusing to publish non-JSON-safe payload to %s: %s", topic, exc)


def publish_tombstone(client, topic: str) -> None:
    """Clear a retained topic with a zero-length retained payload (MQTT's clear semantic).

    Waits up to `TOMBSTONE_WAIT_SECONDS` for the publish so a tombstone is not
    lost on shutdown. Must not be called from the paho network thread (the
    acknowledgement is processed there); the service dispatches inbound
    messages to its own worker for exactly that reason.
    """
    try:
        info = client.publish(topic, payload=None, retain=True, qos=1)
        info.wait_for_publish(timeout=TOMBSTONE_WAIT_SECONDS)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)
