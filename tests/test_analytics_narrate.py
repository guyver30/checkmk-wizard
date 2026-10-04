"""Field-absence tests for analytics.narrate (D-28..D-31).

Narration is template-only: every sentence must be backed by a field in the
input, so each test removes a field and asserts the phrase stating it is gone.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from analytics import narrate

TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 4, 4, 5, tzinfo=UTC)
# 04:02 UTC is 12:02 in Asia/Singapore (UTC+8).
SINCE = "2026-10-04T04:02:00Z"

FULL = {
    "id": "incident-sw1",
    "root": "sw1",
    "root_state": "DOWN",
    "inferred": False,
    "confirmed_down": ["a", "b"],
    "not_observable": ["cam1", "linux1"],
    "dependents": ["x", "y"],
    "worst_criticality": "low",
    "since": SINCE,
}


def _narrate(incident, crit="low"):
    return narrate.incident_narration(incident, crit, NOW, TZ)


def _all_text(result) -> str:
    return " ".join([result["headline"], *result["sentences"]])


def test_d29_snapshot():
    incident = {
        "root": "sw1",
        "root_state": "DOWN",
        "since": SINCE,
        "not_observable": ["cam1", "linux1"],
        "dependents": [],
    }
    result = _narrate(incident)
    assert result["headline"] == "sw1 (low criticality) has been DOWN since 12:02."
    assert result["sentences"] == [
        "2 devices behind it cannot be observed: cam1, linux1.",
        "No dependent devices are affected.",
    ]


def test_headline_only_when_no_list_fields():
    result = _narrate({"root": "sw1", "root_state": "DOWN", "since": SINCE})
    assert result == {
        "headline": "sw1 (low criticality) has been DOWN since 12:02.",
        "sentences": [],
    }


def test_all_list_fields_yield_at_most_three_sentences():
    result = _narrate(FULL)
    assert 1 <= len(result["sentences"]) <= 3
    assert len(result["sentences"]) == 3
    assert result["sentences"][0] == "2 devices behind it are DOWN: a, b."


def test_missing_root_returns_none():
    assert _narrate({"root_state": "DOWN"}) is None
    assert _narrate({"root": "", "root_state": "DOWN"}) is None


@pytest.mark.parametrize(
    "field, absent_phrase",
    [
        ("root_criticality", "criticality"),
        ("since", "since"),
        ("confirmed_down", "are DOWN"),
        ("not_observable", "cannot be observed"),
        ("dependents", "dependent"),
    ],
)
def test_field_absence_removes_phrase(field, absent_phrase):
    full = _narrate(FULL)
    assert absent_phrase in _all_text(full)

    incident = copy.deepcopy(FULL)
    crit = "low"
    if field == "root_criticality":
        crit = None
    else:
        del incident[field]
    reduced = _narrate(incident, crit)
    text = _all_text(reduced)
    if field == "since":
        # The headline falls back to "is DOWN" with no time at all.
        assert reduced["headline"] == "sw1 (low criticality) is DOWN."
    assert absent_phrase not in text


def test_single_device_wording():
    result = _narrate(
        {
            "root": "sw1",
            "root_state": "DOWN",
            "confirmed_down": ["a"],
            "not_observable": ["c"],
            "dependents": ["d"],
        },
        None,
    )
    assert result["sentences"] == [
        "1 device behind it is DOWN: a.",
        "1 device behind it cannot be observed: c.",
        "1 dependent device may be affected: d.",
    ]


def test_dependents_empty_vs_absent():
    empty = _narrate({"root": "sw1", "root_state": "DOWN", "dependents": []})
    assert empty["sentences"] == ["No dependent devices are affected."]
    absent = _narrate({"root": "sw1", "root_state": "DOWN"})
    assert absent["sentences"] == []


def test_name_list_truncates_after_five():
    ids = [f"h{i}" for i in range(8)]
    result = _narrate(
        {"root": "sw1", "root_state": "DOWN", "not_observable": ids}, None
    )
    assert result["sentences"] == [
        "8 devices behind it cannot be observed: h0, h1, h2, h3, h4 and 3 more."
    ]


def test_name_for_maps_ids_to_display_names():
    result = narrate.incident_narration(
        {"root": "sw1", "root_state": "DOWN", "not_observable": ["a"]},
        None,
        NOW,
        TZ,
        name_for=lambda i: f"Name-{i}",
    )
    assert result["headline"] == "Name-sw1 is DOWN."
    assert result["sentences"] == ["1 device behind it cannot be observed: Name-a."]


def test_unreach_root_is_never_down():
    result = _narrate({**FULL, "root_state": "UNREACH", "confirmed_down": []})
    assert result["headline"] == (
        "sw1 (low criticality) has not been observable since 12:02."
    )
    assert "DOWN" not in result["headline"]


def test_inferred_root_is_never_down():
    result = _narrate({**FULL, "inferred": True})
    assert result["headline"] == (
        "sw1 (low criticality) is the inferred common cause since 12:02."
    )
    assert "DOWN" not in result["headline"]


def test_wrong_types_are_skipped():
    result = _narrate(
        {
            "root": "sw1",
            "root_state": "DOWN",
            "confirmed_down": "notalist",
            "not_observable": ["ok", 7, None, ""],
            "dependents": None,
            "since": 12345,
        },
        None,
    )
    assert result["headline"] == "sw1 is DOWN."
    assert result["sentences"] == ["1 device behind it cannot be observed: ok."]


def test_unparseable_since_is_dropped():
    result = _narrate({"root": "sw1", "root_state": "DOWN", "since": "garbage"}, None)
    assert result["headline"] == "sw1 is DOWN."


def test_closed_summary_adds_closing_time_and_duration():
    opened = datetime(2026, 10, 4, 4, 2, tzinfo=UTC)
    closed = datetime(2026, 10, 4, 6, 7, tzinfo=UTC)
    text = narrate.closed_incident_summary(
        {"root": "sw1", "root_state": "DOWN", "not_observable": ["cam1"]},
        "low",
        opened,
        closed,
        "live",
        TZ,
    )
    assert text.startswith("sw1 (low criticality) was DOWN since 12:02.")
    assert "1 device behind it could not be observed: cam1." in text
    assert text.endswith("Closed at 14:07 after 2 h 5 min.")
    assert "offline" not in text


def test_closed_summary_reconcile_note():
    opened = datetime(2026, 10, 4, 4, 2, tzinfo=UTC)
    closed = datetime(2026, 10, 4, 4, 5, tzinfo=UTC)
    text = narrate.closed_incident_summary(
        {"root": "sw1", "root_state": "DOWN"}, None, opened, closed, "reconcile", TZ
    )
    assert "Closed at 12:05 after 3 min." in text
    assert "(closed while analytics was offline; time is when it noticed)" in text


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (10, "under 1 min"),
        (180, "3 min"),
        (2 * 3600 + 5 * 60, "2 h 5 min"),
        (2 * 3600, "2 h"),
        (3 * 86400 + 4 * 3600, "3 d 4 h"),
        (3 * 86400, "3 d"),
    ],
)
def test_format_duration(seconds, expected):
    assert narrate.format_duration(seconds) == expected


def test_need_trend_full():
    text = narrate.need_narration(
        source="trend",
        host="srv1",
        service="Filesystem /",
        unit="%",
        value=85.04,
        crit=90,
        crit_date="2026-11-02",
        confidence="high",
        history_days=14,
    )
    assert text == (
        "srv1 Filesystem / is at 85%; at the current rate it reaches the "
        "critical level (90%) on 2026-11-02 (high confidence, 14 days of history)."
    )


def test_need_trend_without_crit_date_has_no_date_sentence():
    text = narrate.need_narration(
        source="trend",
        host="srv1",
        service="Filesystem /",
        unit="%",
        value=85.5,
        crit=90,
        confidence="high",
        history_days=14,
    )
    assert "reaches" not in text
    assert " on " not in text
    assert "is at 85.5%" in text


def test_need_trend_without_confidence_has_no_parenthetical():
    text = narrate.need_narration(
        source="trend", host="srv1", service="CPU", value=1, crit=2, crit_date="d"
    )
    assert "(" not in text.replace("(2)", "")
    assert "confidence" not in text


def test_need_sustained_with_fraction():
    text = narrate.need_narration(
        source="sustained",
        host="srv1",
        service="CPU",
        unit="%",
        crit=90,
        sustained_fraction=0.75,
        window_hours=24,
    )
    assert text == (
        "srv1 CPU has been at or over the critical level (90%) "
        "for 75% of the last 24 h."
    )


def test_need_sustained_without_fraction():
    text = narrate.need_narration(
        source="sustained", host="srv1", service="CPU", unit="%", value=95, crit=90
    )
    assert text == "srv1 CPU is at 95%, over the critical level (90%)."


def test_need_failure_host_and_service():
    assert (
        narrate.need_narration(source="failure", host="srv1", since=NOW, tz=TZ)
        == "srv1 has been DOWN since 12:05."
    )
    assert (
        narrate.need_narration(
            source="failure", host="srv1", service="Disk", since=NOW, tz=TZ
        )
        == "srv1: Disk is failing since 12:05."
    )
    assert narrate.need_narration(source="failure", host="srv1") == (
        "srv1 has been DOWN."
    )
    assert narrate.need_narration(source="failure", host="srv1", service="Disk") == (
        "srv1: Disk is failing."
    )


def test_no_output_contains_none():
    outputs = [
        _all_text(_narrate({"root": "sw1", "root_state": "DOWN"}, None)),
        _all_text(_narrate({"root": "sw1", "root_state": "UNREACH", "since": None})),
        narrate.closed_incident_summary(
            {"root": "sw1"}, None, NOW, NOW, "reconcile", TZ
        ),
        narrate.need_narration(source="trend", host="h"),
        narrate.need_narration(source="sustained", host="h"),
        narrate.need_narration(source="failure", host="h"),
        narrate.need_narration(source="failure", host="h", service="s"),
    ]
    for text in outputs:
        assert "None" not in text
