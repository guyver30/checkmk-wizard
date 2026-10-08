"""Triage command parsing, application and audit rows (pure, no I/O).

The dashboard publishes a command on `needs/triage/cmd` (QoS 1, not retained);
the browser is untrusted input, so `parse_triage_command` follows the same
discipline as `parse_admin_command` in scripts/mqtt_poller.py: strict shape,
id charset, whitelist of actions, capped free text, capped payload size.

Whether `need_id` names a need that currently exists is the caller's job (the
service holds the tracker); this module only checks its shape. Retained
deliveries are also ignored by the caller.

Idempotence: a downgrade is defined one step below the need's *computed* tier,
not below its current effective tier, so a QoS 1 redelivery (or a second click)
produces the same override instead of stepping down twice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from analytics.rules import Need
from analytics.topics import NEED_ID_RE

TRIAGE_ACTIONS = ("downgrade", "upgrade", "cancel")
MAX_COMMAND_BYTES = 4096
MAX_NOTE_CHARS = 200
MAX_BY_CHARS = 64

_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}\Z")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_DOWNGRADE = {"immediate": "urgent", "urgent": "standard", "standard": "standard"}


class TriageCommandError(ValueError):
    def __init__(self, reason: str, command_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.command_id = command_id


@dataclass(frozen=True)
class TriageCommand:
    id: str
    need_id: str
    action: str
    note: str = ""
    by: str = ""


def _clean_text(value: object, limit: int, field: str, command_id: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TriageCommandError(f"invalid {field}", command_id)
    return _CONTROL_CHARS_RE.sub("", value).strip()[:limit]


def parse_triage_command(payload: bytes) -> TriageCommand:
    if len(payload) > MAX_COMMAND_BYTES:
        raise TriageCommandError("malformed command")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):  # deep nesting raises RecursionError (WR-04)
        raise TriageCommandError("malformed command") from None
    if not isinstance(data, dict):
        raise TriageCommandError("malformed command")
    command_id = data.get("id")
    if not isinstance(command_id, str) or not _COMMAND_ID_RE.match(command_id):
        raise TriageCommandError("malformed command")
    need_id = data.get("need_id")
    if not isinstance(need_id, str) or not NEED_ID_RE.match(need_id):
        raise TriageCommandError("invalid need id", command_id)
    action = data.get("action")
    if action not in TRIAGE_ACTIONS:
        raise TriageCommandError("unknown action", command_id)
    return TriageCommand(
        id=command_id,
        need_id=need_id,
        action=action,
        note=_clean_text(data.get("note"), MAX_NOTE_CHARS, "note", command_id),
        by=_clean_text(data.get("by"), MAX_BY_CHARS, "by", command_id),
    )


def _iso(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_row(
    need: Need,
    action: str,
    tier_before: str,
    tier_after: str,
    now: datetime,
    note: str = "",
    actor: str = "",
    command_id: str = "",
) -> dict:
    return {
        "ts": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "need_id": need.id,
        "source": need.source,
        "host": need.host,
        "service": need.service,
        "metric": need.metric,
        "action": action,
        "computed_tier": need.computed_tier,
        "tier_before": tier_before,
        "tier_after": tier_after,
        "note": note,
        "actor": actor,
        "command_id": command_id,
    }


def apply_triage(need: Need, cmd: TriageCommand, now: datetime) -> tuple[dict, dict]:
    """Return the triage override for `need` and its audit row."""
    if cmd.action == "downgrade":
        tier = _DOWNGRADE.get(need.computed_tier, "standard")
    elif cmd.action == "upgrade":
        tier = "immediate"
    else:
        tier = need.computed_tier
    triage = {
        "action": cmd.action,
        "tier": tier,
        "set_at": _iso(now),
        "computed_tier_at_set": need.computed_tier,
        "note": cmd.note,
        "by": cmd.by,
    }
    row = audit_row(need, cmd.action, need.tier, tier, now, cmd.note, cmd.by, cmd.id)
    return triage, row
