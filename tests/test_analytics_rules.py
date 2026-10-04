"""Tests for analytics.rules: tiering, need identity, anti-flap tracking, triage carry-over."""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from analytics import rules
from analytics.fit import Fit

NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)
TZ = ZoneInfo("Asia/Singapore")
PARAMS = rules.RuleParams(
    trend_need_metrics=frozenset({"disk_used_pct", "smart_wear"}),
    wear_metrics=frozenset({"smart_wear"}),
)


def make_fit(**overrides) -> Fit:
    base = {
        "status": "trending",
        "history_days": 30.0,
        "slope_per_day": 1.0,
        "value_at_end": 80.0,
        "confidence": "medium",
        "last_value": 80.0,
        "warn": 85.0,
        "crit": 90.0,
        "crit_date": "2026-10-14",
        "warn_date": "2026-10-09",
        "days_to_warn": 5.0,
        "days_to_crit": 10.0,
    }
    base.update(overrides)
    return Fit(**base)


def trend(metric="disk_used_pct", **fit_overrides):
    return rules.trend_need("linux1", "Filesystem /", metric, "%", make_fit(**fit_overrides), PARAMS, NOW, TZ)


def sustained(values, latest=None, crit=90.0, warn=85.0, metric="cpu_util"):
    return rules.sustained_need(
        "linux1", "CPU utilization", metric, "%", values, latest, crit, warn, PARAMS, NOW, TZ, 24.0
    )


def make_need(source="trend", host="h1", service="svc", metric="m", tier="urgent", **kw) -> rules.Need:
    return rules.Need(
        id=rules.need_id(source, host, service, metric),
        source=source,
        host=host,
        service=service,
        metric=metric,
        unit="%",
        tier=tier,
        computed_tier=kw.pop("computed_tier", tier),
        since=kw.pop("since", NOW),
        narration="n",
        **kw,
    )


# --- tiers and ids -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "crit,tier",
    [
        ("critical", "immediate"),
        ("high", "urgent"),
        ("medium", "standard"),
        ("low", "standard"),
        (None, "standard"),
        ("bogus", "standard"),
        (5, "standard"),
    ],
)
def test_tier_from_criticality(crit, tier):
    assert rules.tier_from_criticality(crit) == tier


@pytest.mark.parametrize(
    "days,tier",
    [(2.9, "immediate"), (3.0, "urgent"), (20.0, "urgent"), (20.1, "standard"), (90.0, "standard"), (90.1, None)],
)
def test_tier_from_days_bands(days, tier):
    assert rules.tier_from_days(days, PARAMS) == tier


def test_need_id_deterministic_and_shaped():
    a = rules.need_id("trend", "h", "Filesystem /var", "disk_used_pct")
    assert a == rules.need_id("trend", "h", "Filesystem /var", "disk_used_pct")
    assert re.fullmatch(r"[fts]-[0-9a-f]{12}", a)
    assert a.startswith("t-")


def test_need_id_differs_per_source_and_key():
    ids = {
        rules.need_id("trend", "h", "s", "m"),
        rules.need_id("sustained", "h", "s", "m"),
        rules.need_id("failure", "h", "s", "m"),
        rules.need_id("trend", "h2", "s", "m"),
        rules.need_id("trend", "h", "s2", "m"),
    }
    assert len(ids) == 5


# --- trend ---------------------------------------------------------------------------------


def test_trend_need_urgent_for_ten_days():
    need = trend()
    assert need is not None
    assert need.source == "trend"
    assert need.tier == "urgent"
    assert need.computed_tier == "urgent"
    assert need.narration
    assert need.crit_date == "2026-10-14"


def test_trend_need_skips_metric_outside_trend_set():
    assert trend(metric="cpu_util") is None


@pytest.mark.parametrize("status", ["stable", "no_clear_trend"])
def test_trend_need_none_without_trend(status):
    assert trend(status=status) is None


def test_trend_need_none_without_crit_level():
    assert trend(days_to_crit=None, crit=None, crit_date=None) is None


def test_trend_need_none_beyond_horizon():
    assert trend(days_to_crit=120.0) is None


def test_low_confidence_wear_metric_is_capped_at_urgent():
    need = trend(metric="smart_wear", days_to_crit=1.0, confidence="low")
    assert need is not None
    assert need.tier == "urgent"


def test_medium_confidence_wear_metric_is_immediate():
    need = trend(metric="smart_wear", days_to_crit=1.0, confidence="medium")
    assert need is not None
    assert need.tier == "immediate"


def test_low_confidence_non_wear_metric_is_not_capped():
    need = trend(metric="disk_used_pct", days_to_crit=1.0, confidence="low")
    assert need is not None
    assert need.tier == "immediate"


def test_trend_need_none_when_already_breached():
    assert trend(last_value=95.0) is None


# --- sustained -----------------------------------------------------------------------------


def test_sustained_twenty_of_twenty_four():
    values = [95.0] * 20 + [50.0] * 4
    need = sustained(values, latest=95.0)
    assert need is not None
    assert need.source == "sustained"
    assert need.tier == "immediate"
    assert need.sustained_fraction == pytest.approx(0.83, abs=0.005)
    assert need.window_hours == 24
    assert need.narration


def test_sustained_ten_of_twenty_four_is_none():
    values = [95.0] * 10 + [50.0] * 14
    assert sustained(values, latest=50.0) is None


def test_sustained_single_spike_is_none():
    assert sustained([50.0] * 23 + [99.0], latest=99.0) is None


def test_sustained_trend_metric_already_critical_is_immediate_despite_low_fraction():
    need = sustained([50.0] * 23 + [95.0], latest=95.0, metric="disk_used_pct")
    assert need is not None
    assert need.tier == "immediate"


def test_sustained_none_without_crit():
    assert sustained([99.0] * 24, latest=99.0, crit=None) is None


def test_sustained_none_when_crit_below_warn():
    assert sustained([1.0] * 24, latest=1.0, crit=5.0, warn=10.0) is None


def test_sustained_empty_values_is_none():
    assert sustained([], latest=None) is None


# --- failure -------------------------------------------------------------------------------


def _down(host="sw1", state="DOWN"):
    return {host: {"host_state_raw": state}}


def test_failure_need_for_down_host_uses_topology_criticality():
    needs = rules.failure_needs(_down(), {}, {"sw1": {"criticality": "high"}}, {}, NOW, TZ)
    assert len(needs) == 1
    need = needs[0]
    assert need.source == "failure"
    assert need.service == ""
    assert need.tier == "urgent"
    assert need.narration


def test_failure_need_ignores_up_host():
    assert rules.failure_needs(_down(state="UP"), {}, {}, {}, NOW, TZ) == []


@pytest.mark.parametrize("key", ["root", "confirmed_down", "not_observable"])
def test_no_failure_need_for_host_in_open_incident(key):
    incident = {"root": "other", "confirmed_down": [], "not_observable": []}
    incident[key] = "sw1" if key == "root" else ["sw1"]
    assert rules.covered_hosts({"incident-x": incident}) >= {"sw1"}
    assert rules.failure_needs(_down(), {}, {"sw1": {"criticality": "critical"}}, {"incident-x": incident}, NOW, TZ) == []


def test_no_service_failure_need_for_covered_host():
    incident = {"root": "sw1", "confirmed_down": [], "not_observable": []}
    services = {"sw1": [{"description": "TCP Port 443", "state": "CRIT"}]}
    assert rules.failure_needs({"sw1": {"host_state_raw": "UP"}}, services, {}, {"i": incident}, NOW, TZ) == []


@pytest.mark.parametrize("description", ["Systemd Service nginx", "Service Spooler", "TCP Port 443"])
def test_failure_need_for_crit_chosen_service(description):
    services = {"h": [{"description": description, "state": "CRIT"}]}
    needs = rules.failure_needs({"h": {"host_state_raw": "UP"}}, services, {"h": {"criticality": "critical"}}, {}, NOW, TZ)
    assert [n.service for n in needs] == [description]
    assert needs[0].tier == "immediate"


@pytest.mark.parametrize("description", ["Systemd Service Summary", "CPU load"])
def test_no_failure_need_for_unchosen_service(description):
    services = {"h": [{"description": description, "state": "CRIT"}]}
    assert rules.failure_needs({"h": {"host_state_raw": "UP"}}, services, {}, {}, NOW, TZ) == []


def test_no_failure_need_for_ok_service():
    services = {"h": [{"description": "Systemd Service nginx", "state": "OK"}]}
    assert rules.failure_needs({"h": {"host_state_raw": "UP"}}, services, {}, {}, NOW, TZ) == []


def test_service_criticality_overrides_host_value():
    node = {"criticality": "low", "service_criticality": {"Systemd Service nginx": "critical"}}
    services = {"h": [{"description": "Systemd Service nginx", "state": "CRIT"}]}
    (need,) = rules.failure_needs({"h": {"host_state_raw": "UP"}}, services, {"h": node}, {}, NOW, TZ)
    assert need.tier == "immediate"


def test_failure_needs_ignore_malformed_inputs():
    assert rules.failure_needs({"h": "x", "g": {"host_state_raw": "DOWN"}}, {"g": "no", "h": [1, None]}, {"g": []}, {"i": "z"}, NOW, TZ)
    assert rules.covered_hosts({"i": "z", "j": {"root": 3, "confirmed_down": "a", "not_observable": [1]}}) == set()


def test_service_regexes_match_poller():
    spec = importlib.util.spec_from_file_location(
        "mqtt_poller", Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py"
    )
    poller = sys.modules.get("mqtt_poller")
    if poller is None:
        poller = importlib.util.module_from_spec(spec)
        sys.modules["mqtt_poller"] = poller
        spec.loader.exec_module(poller)
    assert rules._CHOSEN_SERVICE_RE.pattern == poller._CHOSEN_SERVICE_RE.pattern
    assert rules._TCP_PORT_SERVICE_RE.pattern == poller._TCP_PORT_SERVICE_RE.pattern


# --- payload -------------------------------------------------------------------------------

# Copied from plan 14.2-06's NeedPayload contract.
NEED_PAYLOAD_KEYS = [
    "id", "source", "host", "service", "metric", "unit", "tier", "computed_tier",
    "days_to_warn", "days_to_crit", "warn_date", "crit_date", "confidence", "history_days",
    "value", "warn", "crit", "sustained_fraction", "window_hours", "since", "narration",
    "triage", "generated_at",
]  # fmt: skip


def test_payload_keys_match_need_payload_contract():
    payload = trend().to_payload()
    assert sorted(payload) == sorted(NEED_PAYLOAD_KEYS)


def test_payload_since_is_iso_utc_z():
    assert make_need(since=NOW).to_payload()["since"] == "2026-10-04T06:00:00Z"


# --- tracker -------------------------------------------------------------------------------


def test_tracker_new_need_since_is_now_then_preserved():
    tracker = rules.NeedTracker(PARAMS)
    publish, tomb = tracker.update([make_need(since=NOW)], NOW)
    assert tomb == [] and publish[0].since == NOW
    later = NOW + timedelta(minutes=15)
    publish, _ = tracker.update([make_need(since=later)], later)
    assert publish[0].since == NOW


def test_tracker_absent_one_cycle_still_published():
    tracker = rules.NeedTracker(PARAMS)
    need = make_need()
    tracker.update([need], NOW)
    publish, tomb = tracker.update([], NOW + timedelta(minutes=15))
    assert [n.id for n in publish] == [need.id]
    assert tomb == []


def test_tracker_tombstones_after_two_absent_cycles_once():
    tracker = rules.NeedTracker(PARAMS)
    need = make_need()
    tracker.update([need], NOW)
    tracker.update([], NOW + timedelta(minutes=15))
    publish, tomb = tracker.update([], NOW + timedelta(minutes=30))
    assert publish == [] and tomb == [need.id]
    _, tomb = tracker.update([], NOW + timedelta(minutes=45))
    assert tomb == []
    assert tracker.get(need.id) is None


def test_tracker_flicker_keeps_triage():
    tracker = rules.NeedTracker(PARAMS)
    need = make_need()
    tracker.update([need], NOW)
    tracker.apply_override(need.id, _triage("downgrade", "standard", "urgent"))
    tracker.update([], NOW + timedelta(minutes=15))
    publish, tomb = tracker.update([make_need()], NOW + timedelta(minutes=30))
    assert tomb == []
    assert publish[0].triage is not None


def test_tracker_recurrence_after_tombstone_is_fresh_and_untriaged():
    tracker = rules.NeedTracker(PARAMS)
    need = make_need()
    tracker.update([need], NOW)
    tracker.apply_override(need.id, _triage("cancel", "urgent", "urgent"))
    tracker.update([], NOW + timedelta(minutes=15))
    tracker.update([], NOW + timedelta(minutes=30))
    back = NOW + timedelta(hours=2)
    publish, _ = tracker.update([make_need(since=back)], back)
    assert publish[0].since == back
    assert publish[0].triage is None


def test_tracker_takes_computed_tier_each_cycle():
    tracker = rules.NeedTracker(PARAMS)
    tracker.update([make_need(tier="immediate")], NOW)
    publish, _ = tracker.update([make_need(tier="standard")], NOW + timedelta(minutes=15))
    assert publish[0].tier == "standard"


def test_tracker_restore_seeds_since_and_triage():
    tracker = rules.NeedTracker(PARAMS)
    old = NOW - timedelta(days=2)
    seeded = make_need(since=old, triage=_triage("downgrade", "standard", "urgent"), tier="standard", computed_tier="urgent")
    tracker.restore([seeded])
    assert tracker.get(seeded.id) is seeded
    publish, _ = tracker.update([make_need(since=NOW)], NOW)
    assert publish[0].since == old
    assert publish[0].triage is not None
    assert publish[0].tier == "standard"


def test_tracker_records_auto_reset_audit():
    tracker = rules.NeedTracker(PARAMS)
    need = make_need(tier="urgent")
    tracker.update([need], NOW)
    tracker.apply_override(need.id, _triage("downgrade", "standard", "urgent"))
    tracker.update([make_need(tier="immediate")], NOW + timedelta(minutes=15))
    assert [a["action"] for _, a in tracker.auto_resets] == ["auto_reset"]


# --- triage carry-over ---------------------------------------------------------------------


def _triage(action, tier, computed_at_set):
    return {
        "action": action,
        "tier": tier,
        "set_at": "2026-10-04T05:00:00Z",
        "computed_tier_at_set": computed_at_set,
        "note": "",
        "by": "op",
    }


def test_carry_triage_kept_when_computed_tier_unchanged():
    prev = make_need(tier="standard", computed_tier="urgent", triage=_triage("downgrade", "standard", "urgent"))
    new, audit = rules.carry_triage(prev, make_need(tier="urgent"))
    assert audit is None
    assert new.triage == prev.triage
    assert new.tier == "standard"
    assert new.computed_tier == "urgent"


def test_carry_triage_dropped_when_computed_tier_worsens():
    prev = make_need(tier="standard", computed_tier="urgent", triage=_triage("downgrade", "standard", "urgent"))
    new, audit = rules.carry_triage(prev, make_need(tier="immediate"))
    assert new.triage is None
    assert new.tier == "immediate"
    assert audit == {
        "action": "auto_reset",
        "tier_before": "standard",
        "tier_after": "immediate",
        "computed_tier": "immediate",
    }


def test_carry_triage_kept_when_computed_tier_improves():
    prev = make_need(tier="immediate", computed_tier="urgent", triage=_triage("upgrade", "immediate", "urgent"))
    new, audit = rules.carry_triage(prev, make_need(tier="standard"))
    assert audit is None
    assert new.tier == "immediate"


def test_carry_triage_cancel_kept_and_tier_stays_computed():
    prev = make_need(tier="urgent", triage=_triage("cancel", "urgent", "urgent"))
    new, audit = rules.carry_triage(prev, make_need(tier="urgent"))
    assert audit is None
    assert new.triage["action"] == "cancel"
    assert new.tier == "urgent"


def test_carry_triage_without_previous():
    new, audit = rules.carry_triage(None, make_need())
    assert audit is None and new.triage is None
