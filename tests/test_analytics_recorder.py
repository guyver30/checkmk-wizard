"""Tests for analytics.recorder: event dedup and incident open/close rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from analytics.recorder import EventRecorder, IncidentRecorder

TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)


def _events(*entries) -> bytes:
    return json.dumps(list(entries)).encode()


def _ev(device="sw1", ts="2026-10-04T05:00:00Z", event="state_change", frm="UP", to="DOWN"):
    return {"timestamp": ts, "device_id": device, "event": event, "from": frm, "to": to}


def test_same_array_twice_yields_rows_once():
    rec = EventRecorder(set())
    payload = _events(_ev())
    assert len(rec.new_rows(payload)) == 1
    assert rec.new_rows(payload) == []


def test_cascade_same_timestamp_all_recorded():
    rec = EventRecorder(set())
    rows = rec.new_rows(_events(_ev("a"), _ev("b"), _ev("c")))
    assert [r["device_id"] for r in rows] == ["a", "b", "c"]


def test_seeded_keys_skipped_and_null_states_blank():
    rec = EventRecorder({("2026-10-04 05:00:00", "sw1", "state_change", "UP", "DOWN")})
    rows = rec.new_rows(_events(_ev(), _ev("n", event="added", frm=None, to=None)))
    assert len(rows) == 1
    assert rows[0]["from_state"] == "" and rows[0]["to_state"] == ""
    assert rows[0]["ts"] == "2026-10-04 05:00:00"


def test_malformed_payloads_give_no_rows():
    rec = EventRecorder(set())
    assert rec.new_rows(b"not json") == []
    assert rec.new_rows(b"{}") == []
    assert rec.new_rows(b"\xff") == []
    assert rec.new_rows(b"[" + b"0," * 5000 + b"0]") == []
    assert rec.new_rows(b" " * (1024 * 1024 + 1)) == []
    assert rec.new_rows(_events({"device_id": "x"}, {"timestamp": "2026-10-04T05:00:00Z"}, "junk")) == []


INCIDENT = {
    "id": "inc-1",
    "root": "sw1",
    "root_state": "DOWN",
    "inferred": False,
    "confirmed_down": ["sw1"],
    "not_observable": [],
    "dependents": ["a"],
    "worst_criticality": "high",
    "since": "2026-10-04T05:30:00Z",
}


def test_open_then_same_then_changed():
    rec = IncidentRecorder(TZ)
    row = rec.on_status("inc-1", INCIDENT, NOW, "high")
    assert row["status"] == "open" and row["opened_at"] == "2026-10-04 05:30:00"
    assert row["closed_at"] is None and "sw1" in row["summary"]
    assert rec.on_status("inc-1", INCIDENT, NOW, "high") is None
    changed = {**INCIDENT, "not_observable": ["pc"]}
    row2 = rec.on_status("inc-1", changed, NOW + timedelta(minutes=1), "high")
    assert row2["opened_at"] == row["opened_at"] and row2["not_observable"] == ["pc"]


def test_tombstone_closes_with_duration_and_summary():
    rec = IncidentRecorder(TZ)
    rec.on_status("inc-1", INCIDENT, NOW, "high")
    row = rec.on_tombstone("inc-1", NOW + timedelta(minutes=30), "high")
    assert row["status"] == "closed" and row["close_source"] == "tombstone"
    assert row["duration_s"] == 3600
    assert row["closed_at"] == "2026-10-04 06:30:00"
    assert "Closed at" in row["summary"]
    assert rec.on_tombstone("inc-1", NOW, None) is None
    assert rec.on_tombstone("unknown", NOW, None) is None


def _seed_row(incident_id="inc-1", opened="2026-10-04 05:00:00"):
    return {
        "incident_id": incident_id,
        "opened_at": opened,
        "closed_at": None,
        "duration_s": None,
        "status": "open",
        "root": "sw1",
        "root_state": "DOWN",
        "inferred": "0",
        "confirmed_down": ["sw1"],
        "not_observable": [],
        "dependents": [],
        "worst_criticality": "high",
        "summary": "x",
    }


def test_reconcile_closes_unretained_keeps_retained():
    rec = IncidentRecorder(TZ)
    rec.seed_open([_seed_row("inc-1"), _seed_row("inc-2")])
    rows = rec.reconcile({"inc-2"}, NOW)
    assert len(rows) == 1
    assert rows[0]["incident_id"] == "inc-1"
    assert rows[0]["close_source"] == "reconcile"
    assert rows[0]["duration_s"] == 3600
    assert rec.reconcile({"inc-2"}, NOW) == []


def test_seeded_unchanged_status_not_rewritten():
    rec = IncidentRecorder(TZ)
    rec.seed_open([_seed_row()])
    incident = {**INCIDENT, "dependents": []}
    assert rec.on_status("inc-1", incident, NOW, "high") is None
