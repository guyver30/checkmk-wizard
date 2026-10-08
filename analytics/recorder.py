"""Row generation for durable event and incident history (pure, no I/O).

`EventRecorder` turns the bounded `lan/events/recent` array into
`history.events` rows, once each. `IncidentRecorder` turns incident status
messages and their tombstones into `history.incidents` rows (open on first
sight, updated when the content changes, closed with the D-30 summary on
tombstone, or closed with close_source 'reconcile' when an incident stored open
is no longer retained after a restart). The service performs the actual writes
through analytics/history.py.

Events are deduplicated on the full key (timestamp, device_id, event,
from_state, to_state), not a timestamp watermark: a cascade stamps several
devices with the same timestamp, and a watermark would drop all but the first.
The key set is seeded from the last two days of history. The poller keeps only
the last 1000 events, so a gap during an analytics outage longer than that is
accepted until the deferred transport phase.

Payloads come from the broker and are untrusted: oversized or malformed input
yields no rows instead of raising.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, tzinfo

from analytics.narrate import closed_incident_summary, incident_narration

MAX_EVENTS_PAYLOAD_BYTES = 1024 * 1024
MAX_EVENTS = 5000

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ch_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TS_FORMAT)


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


class EventRecorder:
    def __init__(self, seed_keys: set[tuple] | None = None) -> None:
        self._seen: set[tuple] = set(seed_keys or ())

    def new_rows(self, payload: bytes) -> list[dict]:
        if len(payload) > MAX_EVENTS_PAYLOAD_BYTES:
            return []
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):  # deep nesting raises RecursionError (WR-04)
            return []
        if not isinstance(data, list) or len(data) > MAX_EVENTS:
            return []
        rows: list[dict] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            moment = _parse_iso(entry.get("timestamp"))
            device_id = entry.get("device_id")
            if moment is None or not isinstance(device_id, str) or not device_id:
                continue
            row = {
                "ts": _ch_time(moment),
                "device_id": device_id,
                "event": _text(entry.get("event")),
                "from_state": _text(entry.get("from")),
                "to_state": _text(entry.get("to")),
            }
            key = (row["ts"], row["device_id"], row["event"], row["from_state"], row["to_state"])
            if key in self._seen:
                continue
            self._seen.add(key)
            rows.append(row)
        return rows


def _content(incident: dict) -> tuple:
    """Fields whose change rewrites the open row (`since` is the open time, not content)."""
    return (
        incident.get("root"),
        incident.get("root_state"),
        bool(incident.get("inferred")),
        tuple(incident.get("confirmed_down") or ()),
        tuple(incident.get("not_observable") or ()),
        tuple(incident.get("dependents") or ()),
        incident.get("worst_criticality"),
    )


def _incident_from_row(row: dict) -> dict:
    return {
        "root": row.get("root"),
        "root_state": row.get("root_state"),
        "inferred": bool(int(row.get("inferred") or 0)),
        "confirmed_down": list(row.get("confirmed_down") or []),
        "not_observable": list(row.get("not_observable") or []),
        "dependents": list(row.get("dependents") or []),
        "worst_criticality": row.get("worst_criticality"),
    }


class IncidentRecorder:
    def __init__(self, tz: tzinfo) -> None:
        self.tz = tz
        # incident_id -> (opened_at, incident dict, root criticality)
        self._open: dict[str, tuple[datetime, dict, str | None]] = {}

    def seed_open(self, rows: list[dict]) -> None:
        for row in rows:
            incident_id = row.get("incident_id")
            opened_at = _parse_iso(_text(row.get("opened_at")).replace(" ", "T"))
            if not isinstance(incident_id, str) or opened_at is None:
                continue
            self._open[incident_id] = (
                opened_at,
                _incident_from_row(row),
                row.get("worst_criticality") or None,
            )

    def _row(self, incident_id: str, opened_at: datetime, incident: dict, summary: str, now: datetime) -> dict:
        return {
            "incident_id": incident_id,
            "opened_at": _ch_time(opened_at),
            "closed_at": None,
            "duration_s": None,
            "status": "open",
            "close_source": "",
            "root": _text(incident.get("root")),
            "root_state": _text(incident.get("root_state")),
            "inferred": 1 if incident.get("inferred") else 0,
            "confirmed_down": list(incident.get("confirmed_down") or []),
            "not_observable": list(incident.get("not_observable") or []),
            "dependents": list(incident.get("dependents") or []),
            "worst_criticality": _text(incident.get("worst_criticality")),
            "summary": summary,
            "updated_at": _ch_time(now),
        }

    def on_status(
        self, incident_id: str, incident: dict, now: datetime, root_criticality: str | None
    ) -> dict | None:
        if not isinstance(incident, dict):
            return None
        known = self._open.get(incident_id)
        if known is not None and _content(known[1]) == _content(incident):
            return None
        opened_at = known[0] if known else (_parse_iso(incident.get("since")) or now)
        narration = incident_narration(incident, root_criticality, now, self.tz)
        summary = narration["headline"] if narration else ""
        self._open[incident_id] = (opened_at, dict(incident), root_criticality)
        return self._row(incident_id, opened_at, incident, summary, now)

    def _close(self, incident_id: str, now: datetime, source: str, root_criticality: str | None) -> dict:
        opened_at, incident, criticality = self._open.pop(incident_id)
        summary = closed_incident_summary(incident, root_criticality or criticality, opened_at, now, source, self.tz)
        row = self._row(incident_id, opened_at, incident, summary, now)
        row.update(
            closed_at=_ch_time(now),
            duration_s=max(0, int((now - opened_at).total_seconds())),
            status="closed",
            close_source=source,
        )
        return row

    def on_tombstone(self, incident_id: str, now: datetime, root_criticality: str | None) -> dict | None:
        if incident_id not in self._open:
            return None
        return self._close(incident_id, now, "tombstone", root_criticality)

    def reconcile(self, retained_ids: set[str], now: datetime) -> list[dict]:
        return [self._close(i, now, "reconcile", None) for i in sorted(self._open) if i not in retained_ids]
