"""Tests for analytics.triage: command validation, application, audit rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from analytics import rules
from analytics.triage import (
    TriageCommand,
    TriageCommandError,
    apply_triage,
    audit_row,
    parse_triage_command,
)

NOW = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)
NEED_ID = "f-0123456789ab"


def _payload(**overrides) -> bytes:
    data = {"id": "cmd-1", "need_id": NEED_ID, "action": "downgrade", "note": "ok", "by": "kone"}
    data.update(overrides)
    return json.dumps(data).encode()


def _need(tier="immediate", computed=None):
    need = rules._make("failure", "sw1", "", "", "", computed or tier, NOW, None)
    need.tier = tier
    return need


def test_valid_command():
    cmd = parse_triage_command(_payload())
    assert cmd == TriageCommand("cmd-1", NEED_ID, "downgrade", "ok", "kone")


def test_note_and_by_trimmed_cleaned_capped():
    cmd = parse_triage_command(_payload(note="  " + "x" * 300, by="a\x00b\n" + "y" * 100))
    assert len(cmd.note) == 200
    assert cmd.by.startswith("ab") and len(cmd.by) == 64


@pytest.mark.parametrize(
    "raw",
    [b"\xff", b"nope", b"[]", b'"x"', _payload(id="bad id!"), _payload(id=5), b" " * 5000],
)
def test_malformed_has_no_command_id(raw):
    with pytest.raises(TriageCommandError) as err:
        parse_triage_command(raw)
    assert err.value.command_id is None


def test_unknown_action_carries_command_id():
    with pytest.raises(TriageCommandError) as err:
        parse_triage_command(_payload(action="delete"))
    assert err.value.command_id == "cmd-1"


@pytest.mark.parametrize("need_id", ["x-0123456789ab", "f-xyz", 7, "f-0123456789abc"])
def test_bad_need_id_rejected(need_id):
    with pytest.raises(TriageCommandError) as err:
        parse_triage_command(_payload(need_id=need_id))
    assert err.value.command_id == "cmd-1"


def test_non_string_note_rejected():
    with pytest.raises(TriageCommandError):
        parse_triage_command(_payload(note=5))


@pytest.mark.parametrize(
    "computed,expected", [("immediate", "urgent"), ("urgent", "standard"), ("standard", "standard")]
)
def test_downgrade_one_step(computed, expected):
    cmd = parse_triage_command(_payload())
    triage, row = apply_triage(_need(computed), cmd, NOW)
    assert triage["tier"] == expected and triage["action"] == "downgrade"
    assert triage["computed_tier_at_set"] == computed
    assert triage["set_at"] == "2026-10-04T06:00:00Z"
    assert triage["note"] == "ok" and triage["by"] == "kone"
    assert row["tier_after"] == expected and row["command_id"] == "cmd-1" and row["actor"] == "kone"


def test_downgrade_is_idempotent_on_redelivery():
    cmd = parse_triage_command(_payload())
    need = _need("immediate")
    first, _ = apply_triage(need, cmd, NOW)
    need.tier = first["tier"]  # the override is now in effect
    second, row = apply_triage(need, cmd, NOW)
    assert second["tier"] == first["tier"] == "urgent"
    assert row["tier_before"] == "urgent"


def test_upgrade_sets_immediate_and_cancel_keeps_computed():
    up, _ = apply_triage(_need("standard"), parse_triage_command(_payload(action="upgrade")), NOW)
    assert up["tier"] == "immediate"
    need = _need("standard", computed="urgent")
    cancel, row = apply_triage(need, parse_triage_command(_payload(action="cancel")), NOW)
    assert cancel["tier"] == "urgent" and cancel["action"] == "cancel"
    assert row["tier_before"] == "standard" and row["tier_after"] == "urgent"


def test_audit_row_auto_reset():
    need = _need("urgent")
    row = audit_row(need, "auto_reset", "standard", "urgent", NOW)
    assert row["action"] == "auto_reset" and row["command_id"] == "" and row["actor"] == ""
    assert row["ts"] == "2026-10-04 06:00:00"
    assert row["need_id"] == need.id and row["computed_tier"] == "urgent"
    assert set(row) == {
        "ts", "need_id", "source", "host", "service", "metric", "action",
        "computed_tier", "tier_before", "tier_after", "note", "actor", "command_id",
    }


def test_override_integrates_with_tracker():
    tracker = rules.NeedTracker(rules.RuleParams())
    need = _need("immediate")
    tracker.restore([need])
    triage, _ = apply_triage(need, parse_triage_command(_payload(need_id=need.id)), NOW)
    tracker.apply_override(need.id, triage)
    assert tracker.get(need.id).tier == "urgent"


def test_deeply_nested_json_is_malformed_not_recursion_error():
    # WR-04: ~4000 '[' fit under MAX_COMMAND_BYTES and made json.loads raise
    # RecursionError, which escaped as a traceback per message.
    with pytest.raises(TriageCommandError):
        parse_triage_command(b"[" * 4000)
