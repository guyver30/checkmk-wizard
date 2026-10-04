"""Tests for analytics.service: routing, recorders, triage, restore and reconcile."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from analytics import topics
from analytics.config import AnalyticsConfig
from analytics.service import INPUT_FILTERS, AnalyticsService

NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)
P = "sites/testsite/"


class FakeInfo:
    def wait_for_publish(self, timeout=None):
        return None


class FakeClient:
    def __init__(self):
        self.published = []  # (topic, payload, qos, retain)
        self.subscribed = []
        self.unsubscribed = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakeInfo()

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def unsubscribe(self, topic):
        self.unsubscribed.append(topic)


class CHError(RuntimeError):
    pass


class FakeHistory:
    ClickHouseError = CHError
    _MIGRATION_HINT = "run the migration"

    def __init__(self):
        self.inserts = []
        self.fail_insert = False
        self.open_incidents = []
        self.event_keys = set()
        self.missing = set()
        self.buckets = {}
        self.levels = {}
        self.hourly = {}
        self.fail_fetch = False

    def insert_rows(self, config, table, rows):
        if self.fail_insert:
            raise CHError("boom")
        self.inserts.append((table, rows))

    def missing_tables(self, config):
        return set(self.missing)

    def fetch_open_incidents(self, config):
        return list(self.open_incidents)

    def fetch_recent_event_keys(self, config, days=2):
        return set(self.event_keys)

    def fetch_fit_buckets(self, config, metrics):
        if self.fail_fetch:
            raise CHError("down")
        return self.buckets

    def fetch_levels(self, config, metrics):
        return self.levels

    def fetch_recent_hourly(self, config, metrics, hours):
        return self.hourly


@pytest.fixture(autouse=True)
def _site():
    topics.set_site_id("testsite")


def msg(rel, payload, retain=False):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return SimpleNamespace(topic=P + rel, payload=body, retain=retain)


def tomb(rel):
    return SimpleNamespace(topic=P + rel, payload=b"", retain=True)


@pytest.fixture
def svc():
    config = AnalyticsConfig(cmk_site_id="testsite", clickhouse_url="http://ch:8123")
    history = FakeHistory()
    service = AnalyticsService(config, history_mod=history, now_fn=lambda: NOW, sleep_fn=lambda s: None)
    service.client = FakeClient()
    return service


INCIDENT = {
    "id": "i1",
    "root": "core",
    "root_state": "DOWN",
    "inferred": False,
    "confirmed_down": ["core"],
    "not_observable": [],
    "dependents": ["sw1"],
    "worst_criticality": "high",
    "since": "2026-10-04T05:00:00Z",
}


def narration_publishes(client, incident_id="i1"):
    topic = f"{P}lan/incidents/{incident_id}/narration"
    return [p for p in client.published if p[0] == topic]


def test_subscriptions_are_specific_never_wildcard_all(svc):
    client = FakeClient()
    svc.on_connect(client, None, None, 0)
    assert client.subscribed == [P + f for f in INPUT_FILTERS]
    assert not any(t.endswith("lan/#") for t in client.subscribed)


def test_foreign_topic_and_malformed_json_ignored(svc):
    svc.on_message(None, None, SimpleNamespace(topic="other/lan/devices/a/status", payload=b"{}", retain=False))
    svc.on_message(None, None, msg("lan/devices/a/status", b"{not json"))
    svc.on_message(None, None, msg("lan/devices/topology", b"[]"))
    assert svc.statuses == {} and svc.topology_nodes == {}


def test_state_updates_and_device_tombstone(svc):
    svc.on_message(None, None, msg("lan/devices/a/status", {"host_state_raw": "DOWN"}))
    svc.on_message(None, None, msg("lan/devices/a/services", [{"description": "x", "state": "OK"}]))
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": "a", "criticality": "high"}]}))
    assert svc.statuses["a"]["host_state_raw"] == "DOWN"
    assert svc.services["a"][0]["state"] == "OK"
    assert svc.topology_nodes["a"]["criticality"] == "high"
    svc.on_message(None, None, tomb("lan/devices/a/status"))
    assert "a" not in svc.statuses


def test_incident_status_records_row_and_publishes_narration(svc):
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": "core", "criticality": "low"}]}))
    svc.on_message(None, None, msg("lan/incidents/i1/status", INCIDENT))
    (table, rows), = svc.history.inserts
    assert table == "history.incidents" and rows[0]["incident_id"] == "i1" and rows[0]["status"] == "open"
    ((_, payload, qos, retain),) = narration_publishes(svc.client)
    body = json.loads(payload)
    assert (qos, retain) == (1, True)
    assert body["id"] == "i1" and body["headline"] and body["tier"] == "urgent"
    assert body["generated_at"] == "2026-10-04T06:00:00Z"


def test_unchanged_repeat_status_publishes_no_second_narration(svc):
    svc.on_message(None, None, msg("lan/incidents/i1/status", INCIDENT))
    svc.on_message(None, None, msg("lan/incidents/i1/status", dict(INCIDENT)))
    assert len(narration_publishes(svc.client)) == 1
    assert len(svc.history.inserts) == 1


def test_status_tombstone_tombstones_narration_and_writes_close_row(svc):
    svc.on_message(None, None, msg("lan/incidents/i1/status", INCIDENT))
    svc.client.published.clear()
    svc.on_message(None, None, tomb("lan/incidents/i1/status"))
    assert svc.client.published == [(f"{P}lan/incidents/i1/narration", None, 1, True)]
    table, rows = svc.history.inserts[-1]
    assert table == "history.incidents" and rows[0]["status"] == "closed"
    assert rows[0]["close_source"] == "tombstone"
    assert "i1" not in svc.open_incidents


def test_events_written_once_and_deduplicated(svc):
    events = [{"timestamp": "2026-10-04T05:00:00Z", "device_id": "sw1", "event": "state_change", "from": "UP", "to": "DOWN"}]
    svc.on_message(None, None, msg("lan/events/recent", events))
    svc.on_message(None, None, msg("lan/events/recent", events))
    assert [t for t, _ in svc.history.inserts] == ["history.events"]


def test_insert_failure_logs_one_warning_and_never_raises(svc, caplog):
    svc.history.fail_insert = True
    svc.history.missing = set()
    svc._missing_tables = {"history.events"}
    events = lambda dev: [{"timestamp": "2026-10-04T05:00:00Z", "device_id": dev, "event": "e", "from": "UP", "to": "DOWN"}]
    with caplog.at_level("WARNING"):
        svc.on_message(None, None, msg("lan/events/recent", events("a")))
        svc.on_message(None, None, msg("lan/events/recent", events("b")))
    warnings = [r for r in caplog.records if "ClickHouse insert" in r.getMessage()]
    assert len(warnings) == 1
    assert "run the migration" in warnings[0].getMessage()


def _seed_need(svc):
    from analytics.rules import failure_needs

    needs = failure_needs({"a": {"host_state_raw": "DOWN"}}, {}, {"a": {"criticality": "critical"}}, {}, NOW, svc.tz)
    svc.tracker.update(needs, NOW)
    return needs[0]


def triage_cmd(need_id, action="downgrade", cid="c1"):
    return {"id": cid, "need_id": need_id, "action": action, "note": "n", "by": "op"}


def test_retained_triage_command_ignored_no_publish_no_insert(svc):
    need = _seed_need(svc)
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd(need.id), retain=True))
    assert svc.client.published == [] and svc.history.inserts == []
    assert svc.tracker.get(need.id).triage is None


def test_malformed_triage_command_logged_nothing_published(svc, caplog):
    with caplog.at_level("WARNING"):
        svc.on_message(None, None, msg("needs/triage/cmd", {"id": "c9", "need_id": "bogus", "action": "downgrade"}))
    assert svc.client.published == [] and svc.history.inserts == []
    assert any("c9" in r.getMessage() for r in caplog.records)


def test_unknown_need_ignored(svc):
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd("f-" + "0" * 12)))
    assert svc.client.published == [] and svc.history.inserts == []


def test_valid_triage_applies_audits_and_republishes(svc):
    need = _seed_need(svc)
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd(need.id)))
    table, rows = svc.history.inserts[-1]
    assert table == "history.need_triage" and rows[0]["action"] == "downgrade" and rows[0]["command_id"] == "c1"
    ((topic, payload, _, retain),) = svc.client.published
    body = json.loads(payload)
    assert topic == f"{P}lan/needs/{need.id}/status" and retain
    assert body["tier"] == "urgent" and body["triage"]["action"] == "downgrade"
    assert body["generated_at"] == "2026-10-04T06:00:00Z"


def test_restore_seeds_tracker_and_reconcile_closes_stale_incidents(svc):
    need = _seed_need(svc)
    payload = need.to_payload()
    payload["generated_at"] = "2026-10-04T05:59:00Z"
    svc.history.open_incidents = [
        {
            "incident_id": "stale",
            "opened_at": "2026-10-04 04:00:00",
            "root": "core",
            "root_state": "DOWN",
            "inferred": 0,
            "confirmed_down": ["core"],
            "not_observable": [],
            "dependents": [],
            "worst_criticality": "high",
        }
    ]
    fresh = AnalyticsService(svc.config, history_mod=svc.history, now_fn=lambda: NOW, sleep_fn=lambda s: None)
    fresh.client = FakeClient()
    fresh._seed_from_history()
    # Retained replay arrives while the restore window is open.
    def sleep(_):
        fresh.on_message(None, None, msg(f"lan/needs/{need.id}/status", payload))
        fresh.on_message(None, None, msg("lan/incidents/orphan/narration", {"id": "orphan"}))
        fresh.on_message(None, None, msg("lan/incidents/live/narration", {"id": "live"}))
        fresh.on_message(None, None, msg("lan/incidents/live/status", INCIDENT))

    fresh._sleep = sleep
    fresh.restore()
    fresh.reconcile()
    assert fresh.tracker.get(need.id) is not None
    assert fresh.client.subscribed == [P + "lan/needs/+/status", P + "lan/incidents/+/narration"]
    assert fresh.client.unsubscribed == fresh.client.subscribed
    closed = [r for t, rows in fresh.history.inserts if t == "history.incidents" for r in rows if r["status"] == "closed"]
    assert [(r["incident_id"], r["close_source"]) for r in closed] == [("stale", "reconcile")]
    tombstoned = [p[0] for p in fresh.client.published if p[1] is None]
    assert tombstoned == [f"{P}lan/incidents/orphan/narration"]


def test_need_payload_roundtrip_ignores_garbage():
    from analytics.service import need_from_payload

    assert need_from_payload("x", None) is None
    assert need_from_payload({"id": "bad", "source": "failure"}, None) is None
