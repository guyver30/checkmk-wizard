"""Tests for analytics.publish: retained JSON and tombstone helpers."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from analytics.publish import (
    content_event_id,
    publish_retained_json,
    publish_tombstone,
)

_SPEC = importlib.util.spec_from_file_location(
    "mqtt_poller_for_publish",
    Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py",
)
poller = importlib.util.module_from_spec(_SPEC)
sys.modules["mqtt_poller_for_publish"] = poller
_SPEC.loader.exec_module(poller)


class _Info:
    def __init__(self):
        self.waited = None

    def wait_for_publish(self, timeout=None):
        self.waited = timeout


class _Client:
    def __init__(self, error=None):
        self.calls = []
        self.properties = []
        self.error = error
        self.info = _Info()

    def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
        if self.error:
            raise self.error
        self.properties.append(properties)
        self.calls.append((topic, payload, qos, retain))
        return self.info


def test_retained_json_is_compact_qos1_retained():
    client = _Client()
    publish_retained_json(client, "t/x", {"a": 1, "b": [1, 2]})
    topic, payload, qos, retain = client.calls[0]
    assert (topic, qos, retain) == ("t/x", 1, True)
    assert payload == '{"a":1,"b":[1,2]}'
    assert json.loads(payload) == {"a": 1, "b": [1, 2]}


def test_retained_json_logs_not_raises_on_broker_error():
    publish_retained_json(_Client(error=OSError("down")), "t/x", {})
    publish_retained_json(_Client(error=TimeoutError()), "t/x", {})


def test_retained_json_refuses_non_finite():
    client = _Client()
    publish_retained_json(client, "t/x", {"a": float("nan")})
    assert client.calls == []


def test_tombstone_is_empty_retained_and_waits_five_seconds():
    client = _Client()
    publish_tombstone(client, "t/x")
    assert client.calls == [("t/x", None, 1, True)]
    assert client.info.waited == 5


def test_tombstone_swallows_broker_error():
    publish_tombstone(_Client(error=OSError("down")), "t/x")


def test_content_event_id_is_key_order_independent_and_content_sensitive():
    a = content_event_id("n1", {"b": 1, "a": 2})
    assert a == content_event_id("n1", {"a": 2, "b": 1})
    assert a != content_event_id("n1", {"a": 3, "b": 1})
    assert re.fullmatch(r"n1-[0-9a-f]{16}", a)


def test_content_event_id_matches_poller_format():
    for prefix, payload in [("n1", {"a": 1}), ("h-forecast", {"x": [1, 2], "y": "z"})]:
        assert content_event_id(prefix, payload) == poller.content_event_id(
            prefix, payload
        )


def test_retained_json_attaches_event_id_user_property():
    client = _Client()
    publish_retained_json(client, "t/x", {"a": 1}, event_id="E")
    assert client.properties[0].UserProperty == [("event_id", "E")]
    assert client.calls[0] == ("t/x", '{"a":1}', 1, True)


def test_retained_json_without_event_id_has_no_properties():
    client = _Client()
    publish_retained_json(client, "t/x", {"a": 1})
    assert client.properties == [None]


def test_tombstone_attaches_event_id_user_property():
    client = _Client()
    publish_tombstone(client, "t/x", event_id="T")
    assert client.properties[0].UserProperty == [("event_id", "T")]
    assert client.calls == [("t/x", None, 1, True)]
    assert client.info.waited == 5


def test_tombstone_without_event_id_has_no_properties():
    client = _Client()
    publish_tombstone(client, "t/x")
    assert client.properties == [None]
