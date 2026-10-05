"""Tests for analytics.service: routing, recorders, triage, restore and reconcile."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from analytics import topics
from analytics.config import FALLBACK_LEVELS, AnalyticsConfig
from analytics.service import INPUT_FILTERS, AnalyticsService, iso_utc

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


# --- evaluation cycle ---------------------------------------------------------

NOW_TS = int(NOW.timestamp())


def _ramp(start=30.0, step=0.5, count=80):
    return [(NOW_TS - (count - i) * 6 * 3600, start + i * step) for i in range(count)]


def _noise(count=80):
    return [(NOW_TS - (count - i) * 6 * 3600, 40.0 if i % 2 else 60.0) for i in range(count)]


def published_json(client, prefix):
    return {
        topic: json.loads(payload)
        for topic, payload, _, _ in client.published
        if topic.startswith(P + prefix) and payload is not None
    }


@pytest.fixture
def cycle_svc(svc):
    svc.history.buckets = {
        ("srv1", "Filesystem /", "fs_used_percent"): _ramp(),
        ("srv1", "Memory", "mem_used_percent"): _noise(),
        ("srv2", "CPU utilization", "util"): _ramp(start=10, step=0.0, count=80),
    }
    svc.history.levels = {
        ("srv1", "Filesystem /", "fs_used_percent"): (80.0, 90.0),
        ("srv1", "Memory", "mem_used_percent"): (80.0, 90.0),
        ("srv2", "CPU utilization", "util"): (None, None),
    }
    return svc


def test_cycle_ramp_publishes_trend_need_and_noise_gets_fit_without_need(cycle_svc):
    cycle_svc.run_cycle(NOW)
    needs = published_json(cycle_svc.client, "lan/needs/")
    assert len(needs) == 1
    ((topic, need),) = needs.items()
    assert re.fullmatch(P + r"lan/needs/t-[0-9a-f]{12}/status", topic)
    assert need["source"] == "trend" and need["host"] == "srv1" and need["generated_at"] == iso_utc(NOW)
    forecast = published_json(cycle_svc.client, "lan/forecasts/srv1")[P + "lan/forecasts/srv1"]
    by_metric = {f["metric"]: f for f in forecast["fits"]}
    assert by_metric["mem_used_percent"]["status"] == "no_clear_trend"
    assert by_metric["fs_used_percent"]["status"] == "trending"
    assert forecast["host"] == "srv1" and forecast["generated_at"] == iso_utc(NOW)
    assert P + "lan/forecasts/srv2" in published_json(cycle_svc.client, "lan/forecasts/")


def test_cycle_fallback_levels_only_when_checkmk_gives_none(cycle_svc):
    cycle_svc.run_cycle(NOW)
    forecasts = published_json(cycle_svc.client, "lan/forecasts/")
    util = forecasts[P + "lan/forecasts/srv2"]["fits"][0]
    assert (util["warn"], util["crit"]) == FALLBACK_LEVELS["util"]
    fs = next(f for f in forecasts[P + "lan/forecasts/srv1"]["fits"] if f["metric"] == "fs_used_percent")
    assert (fs["warn"], fs["crit"]) == (80.0, 90.0)


def test_cycle_sustained_breach_raises_immediate_need(cycle_svc):
    cycle_svc.history.hourly = {("srv2", "CPU utilization", "util"): [(NOW_TS - h * 3600, 99.0) for h in range(24)]}
    cycle_svc.run_cycle(NOW)
    needs = published_json(cycle_svc.client, "lan/needs/")
    sustained = [n for n in needs.values() if n["source"] == "sustained"]
    assert len(sustained) == 1 and sustained[0]["tier"] == "immediate" and sustained[0]["host"] == "srv2"


def test_cycle_clickhouse_down_still_publishes_failure_need(svc):
    svc.history.fail_fetch = True
    svc.on_message(None, None, msg("lan/devices/h1/status", {"host_state_raw": "DOWN"}))
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": "h1", "criticality": "critical"}]}))
    svc.run_cycle(NOW)
    needs = published_json(svc.client, "lan/needs/")
    assert len(needs) == 1
    (need,) = needs.values()
    assert need["source"] == "failure" and need["tier"] == "immediate"
    assert published_json(svc.client, "lan/forecasts/") == {}


def test_cycle_outage_does_not_resolve_trend_needs(cycle_svc):
    cycle_svc.run_cycle(NOW)
    cycle_svc.history.fail_fetch = True
    cycle_svc.client.published.clear()
    for _ in range(3):
        cycle_svc.run_cycle(NOW)
    assert [p for p in cycle_svc.client.published if p[1] is None] == []
    assert len(published_json(cycle_svc.client, "lan/needs/")) == 1


def test_cycle_tombstones_resolved_need_after_clean_cycles_and_vanished_forecast(cycle_svc):
    cycle_svc.run_cycle(NOW)
    cycle_svc.history.buckets = {}
    cycle_svc.client.published.clear()
    cycle_svc.run_cycle(NOW)
    cycle_svc.run_cycle(NOW)
    tombstones = {p[0] for p in cycle_svc.client.published if p[1] is None}
    assert any(t.startswith(P + "lan/needs/t-") for t in tombstones)
    assert {P + "lan/forecasts/srv1", P + "lan/forecasts/srv2"} <= tombstones


def test_cycle_unsafe_host_gets_no_forecast_topic(cycle_svc):
    cycle_svc.history.buckets = {("bad/host", "s", "util"): _noise()}
    cycle_svc.run_cycle(NOW)
    assert published_json(cycle_svc.client, "lan/forecasts/") == {}


def test_cycle_writes_auto_reset_audit_row(svc):
    svc.on_message(None, None, msg("lan/devices/h1/status", {"host_state_raw": "DOWN"}))
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": "h1", "criticality": "low"}]}))
    svc.run_cycle(NOW)
    (need_id,) = [t.split("/")[-2] for t in published_json(svc.client, "lan/needs/")]
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd(need_id, "cancel")))
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd(need_id, "downgrade", "c2")))
    # Computed tier gets worse than at triage time: the override must be dropped and audited.
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": "h1", "criticality": "critical"}]}))
    svc.history.inserts.clear()
    svc.run_cycle(NOW)
    rows = [r for t, rows in svc.history.inserts if t == "history.need_triage" for r in rows]
    assert [r["action"] for r in rows] == ["auto_reset"]
    assert rows[0]["actor"] == "" and rows[0]["command_id"] == ""


def test_run_forever_runs_cycles_and_ticks_rollups_until_stopped(svc):
    calls = {"cycles": 0, "rollups": 0}
    clock_value = [0.0]

    class FakeStop:
        def __init__(self):
            self.stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, timeout=None):
            clock_value[0] += svc.config.eval_interval_seconds

    class FakeRollup:
        class RollupScheduler:
            def __init__(self, delay_minutes):
                self.delay_minutes = delay_minutes

        @staticmethod
        def maybe_run_rollups(config, scheduler, holder, tz, now_local, now_monotonic):
            calls["rollups"] += 1

    stop = FakeStop()

    def run_cycle(now, slow=True):
        calls["cycles"] += 1
        if calls["cycles"] == 2:
            stop.stopped = True

    svc.rollup_mod = FakeRollup
    svc.run_cycle = run_cycle
    svc.run_forever(stop, clock=lambda: clock_value[0])
    assert calls["cycles"] == 2 and calls["rollups"] >= 2


def test_main_rejects_invalid_site_id(monkeypatch, capsys):
    from analytics.service import main

    monkeypatch.setenv("CMK_SITE_ID", "1bad")
    assert main() == 2
    assert "error:" in capsys.readouterr().err


def _down_host(svc, host="h1", criticality="critical"):
    svc.on_message(None, None, msg(f"lan/devices/{host}/status", {"host_state_raw": "DOWN"}))
    svc.on_message(None, None, msg("lan/devices/topology", {"devices": [{"id": host, "criticality": criticality}]}))


def _tombstoned_need_topics(client):
    return [p[0] for p in client.published if p[1] is None and p[0].startswith(P + "lan/needs/")]


def test_fast_tick_publishes_failure_need_without_touching_history(svc):
    def boom(*args, **kwargs):
        raise AssertionError("fast tick must not query ClickHouse")

    svc.history.fetch_fit_buckets = boom
    svc.history.fetch_levels = boom
    svc.history.fetch_recent_hourly = boom
    _down_host(svc)
    svc.run_cycle(NOW, slow=False)
    (need,) = published_json(svc.client, "lan/needs/").values()
    assert need["source"] == "failure" and need["tier"] == "immediate"
    assert published_json(svc.client, "lan/forecasts/") == {}


def test_fast_ticks_keep_slow_needs_open(cycle_svc):
    cycle_svc.run_cycle(NOW)
    (trend_id,) = [n["id"] for n in published_json(cycle_svc.client, "lan/needs/").values()]
    cycle_svc.history.buckets = {}
    cycle_svc.client.published.clear()
    for _ in range(5):
        cycle_svc.run_cycle(NOW, slow=False)
    assert _tombstoned_need_topics(cycle_svc.client) == []
    assert cycle_svc.tracker.get(trend_id) is not None
    # Unchanged needs are not republished on fast ticks.
    assert published_json(cycle_svc.client, "lan/needs/") == {}


def test_failure_need_clears_after_two_fast_ticks(svc):
    _down_host(svc)
    svc.run_cycle(NOW, slow=False)
    svc.on_message(None, None, msg("lan/devices/h1/status", {"host_state_raw": "UP"}))
    svc.client.published.clear()
    svc.run_cycle(NOW, slow=False)
    assert _tombstoned_need_topics(svc.client) == []
    svc.run_cycle(NOW, slow=False)
    assert len(_tombstoned_need_topics(svc.client)) == 1


def test_covered_down_host_gets_need_and_triage_is_audited(svc):
    svc.on_message(None, None, msg("lan/incidents/i1/status", INCIDENT))
    _down_host(svc, host="core", criticality="high")
    svc.run_cycle(NOW, slow=False)
    (need,) = published_json(svc.client, "lan/needs/").values()
    assert need["host"] == "core" and need["tier"] == "urgent"
    svc.client.published.clear()
    svc.on_message(None, None, msg("needs/triage/cmd", triage_cmd(need["id"])))
    table, rows = svc.history.inserts[-1]
    assert table == "history.need_triage" and rows[0]["action"] == "downgrade"
    (republished,) = published_json(svc.client, "lan/needs/").values()
    assert republished["tier"] == "standard" and republished["triage"]["action"] == "downgrade"


def test_run_forever_schedule_one_slow_then_fast_ticks(svc):
    calls = []
    clock_value = [0.0]

    class FakeStop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, timeout=None):
            clock_value[0] += timeout

    class FakeRollup:
        class RollupScheduler:
            def __init__(self, delay_minutes):
                pass

        @staticmethod
        def maybe_run_rollups(*args):
            calls.append("rollup")

    stop = FakeStop()

    def run_cycle(now, slow=True):
        calls.append("slow" if slow else "fast")
        if len([c for c in calls if c != "rollup"]) == 61:
            stop.stopped = True

    svc.rollup_mod = FakeRollup
    svc.run_cycle = run_cycle
    svc.run_forever(stop, clock=lambda: clock_value[0])
    cycles = [c for c in calls if c != "rollup"]
    assert cycles[0] == "slow" and set(cycles[1:60]) == {"fast"} and cycles[60] == "slow"
    assert calls.count("rollup") >= 61
