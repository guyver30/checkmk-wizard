"""Tests for analytics.publish: retained JSON and tombstone helpers."""

from __future__ import annotations

import json

from analytics.publish import publish_retained_json, publish_tombstone


class _Info:
    def __init__(self):
        self.waited = None

    def wait_for_publish(self, timeout=None):
        self.waited = timeout


class _Client:
    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.info = _Info()

    def publish(self, topic, payload=None, qos=0, retain=False):
        if self.error:
            raise self.error
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
