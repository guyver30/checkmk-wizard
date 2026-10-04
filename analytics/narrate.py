"""Template-only, English-only narration of incidents and needs (D-28..D-31).

Every sentence comes from a small private function that returns ``None`` when
the field it states is absent, and the public functions keep only the
non-``None`` results. Narration therefore never states a fact the data does
not contain (D-28), and nothing here calls a model or any external service.

Wording discipline follows the header of
``dashboard-react/src/components/IncidentCard.tsx``: a device that is UNREACH
or only inferred as a cause is never described as DOWN; it "cannot be
observed". Open-incident text carries no elapsed duration, because it would go
stale between publishes (the dashboard renders the live elapsed time itself).

Stdlib only; callers pass the ``tzinfo`` used to render clock times.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, tzinfo

_MAX_NAMES = 5
_MAX_SENTENCES = 3


def _num(value: float) -> str:
    """At most one decimal, trailing ".0" dropped."""
    text = f"{round(float(value), 1):.1f}"
    return text.removesuffix(".0")


def format_duration(seconds: float) -> str:
    """Render a duration as "3 min", "2 h 5 min" or "3 d 4 h"."""
    total = max(0, int(seconds))
    minutes = total // 60
    if minutes < 1:
        return "under 1 min"
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} min"


def _clock(moment: datetime, tz: tzinfo | None) -> str:
    local = moment.astimezone(tz) if tz is not None else moment
    return local.strftime("%H:%M")


def _since_clock(raw: object, tz: tzinfo | None) -> str | None:
    """HH:MM for an ISO-8601 string (or datetime); None if it does not parse."""
    if isinstance(raw, datetime):
        moment = raw
    elif isinstance(raw, str) and raw:
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        return moment.strftime("%H:%M")
    return _clock(moment, tz)


def _names(value: object, name_for: Callable[[str], str] | None) -> list[str]:
    """Valid display names from a payload list; non-list/non-str entries drop."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(name_for(item) if name_for else item)
    return out


def _name_list(names: list[str]) -> str:
    shown = ", ".join(names[:_MAX_NAMES])
    extra = len(names) - _MAX_NAMES
    return f"{shown} and {extra} more" if extra > 0 else shown


def _headline(
    root: str,
    root_state: object,
    inferred: bool,
    criticality: str | None,
    since_clock: str | None,
    past: bool,
) -> str:
    subject = f"{root} ({criticality} criticality)" if criticality else root
    since = f" since {since_clock}" if since_clock else ""
    if inferred:
        verb = "was" if past else "is"
        return f"{subject} {verb} the inferred common cause{since}."
    if root_state != "DOWN":
        verb = "was not" if past else "has not been"
        return f"{subject} {verb} observable{since}."
    if past:
        return f"{subject} was DOWN{since}."
    if since_clock:
        return f"{subject} has been DOWN{since}."
    return f"{subject} is DOWN."


def _confirmed_sentence(names: list[str], past: bool) -> str | None:
    if not names:
        return None
    n = len(names)
    noun = "device" if n == 1 else "devices"
    verb = ("was" if n == 1 else "were") if past else ("is" if n == 1 else "are")
    return f"{n} {noun} behind it {verb} DOWN: {_name_list(names)}."


def _not_observable_sentence(names: list[str], past: bool) -> str | None:
    if not names:
        return None
    n = len(names)
    noun = "device" if n == 1 else "devices"
    modal = "could not" if past else "cannot"
    return f"{n} {noun} behind it {modal} be observed: {_name_list(names)}."


def _dependents_sentence(incident: dict, name_for, past: bool) -> str | None:
    if "dependents" not in incident or not isinstance(incident["dependents"], list):
        return None
    names = _names(incident["dependents"], name_for)
    if not names:
        return "No dependent devices are affected."
    n = len(names)
    noun = "dependent device" if n == 1 else "dependent devices"
    verb = "may have been" if past else "may be"
    return f"{n} {noun} {verb} affected: {_name_list(names)}."


def _device_sentences(incident: dict, name_for, past: bool) -> list[str]:
    candidates = [
        _confirmed_sentence(_names(incident.get("confirmed_down"), name_for), past),
        _not_observable_sentence(
            _names(incident.get("not_observable"), name_for), past
        ),
        _dependents_sentence(incident, name_for, past),
    ]
    return [s for s in candidates if s][:_MAX_SENTENCES]


def _root_name(incident: dict, name_for) -> str | None:
    root = incident.get("root")
    if not isinstance(root, str) or not root:
        return None
    return name_for(root) if name_for else root


def incident_narration(
    incident: dict,
    root_criticality: str | None,
    now: datetime,
    tz: tzinfo,
    name_for: Callable[[str], str] | None = None,
) -> dict | None:
    """Headline plus 0..3 sentences for an open incident; None without a root.

    ``now`` is accepted for call-site symmetry but unused: open narration
    carries no elapsed duration (it would go stale between publishes).
    """
    root = _root_name(incident, name_for)
    if root is None:
        return None
    headline = _headline(
        root,
        incident.get("root_state"),
        bool(incident.get("inferred")),
        root_criticality,
        _since_clock(incident.get("since"), tz),
        past=False,
    )
    return {
        "headline": headline,
        "sentences": _device_sentences(incident, name_for, past=False),
    }


def closed_incident_summary(
    incident: dict,
    root_criticality: str | None,
    opened_at: datetime,
    closed_at: datetime,
    close_source: str,
    tz: tzinfo,
) -> str:
    """Final summary stored for a closed incident (D-30)."""
    root = _root_name(incident, None) or "An incident"
    parts = [
        _headline(
            root,
            incident.get("root_state"),
            bool(incident.get("inferred")),
            root_criticality,
            _clock(opened_at, tz),
            past=True,
        ),
        *_device_sentences(incident, None, past=True),
    ]
    duration = format_duration((closed_at - opened_at).total_seconds())
    parts.append(f"Closed at {_clock(closed_at, tz)} after {duration}.")
    if close_source == "reconcile":
        parts.append("(closed while analytics was offline; time is when it noticed)")
    return " ".join(parts)


def _crit_clause(crit: float | None, unit: str) -> str | None:
    return f"({_num(crit)}{unit})" if crit is not None else None


def _trend(subject, unit, value, crit, crit_date, confidence, history_days) -> str:
    clauses = []
    if value is not None:
        clauses.append(f"is at {_num(value)}{unit}")
    if crit is not None and crit_date:
        clauses.append(
            "at the current rate it reaches the critical level "
            f"({_num(crit)}{unit}) on {crit_date}"
        )
    body = "; ".join(clauses) if clauses else "is trending toward the critical level"
    if clauses and value is None:
        body = f"is trending: {body}"
    text = f"{subject} {body}"
    if confidence and history_days is not None:
        days = _num(history_days)
        unit_word = "day" if days == "1" else "days"
        text += f" ({confidence} confidence, {days} {unit_word} of history)"
    return text + "."


def _sustained(subject, unit, value, crit, fraction, window_hours) -> str:
    level = _crit_clause(crit, unit)
    level_text = f"the critical level {level}" if level else "the critical level"
    if fraction is not None:
        window = (
            f"the last {_num(window_hours)} h"
            if window_hours is not None
            else "the observed window"
        )
        return (
            f"{subject} has been at or over {level_text} "
            f"for {_num(fraction * 100)}% of {window}."
        )
    if value is not None:
        return f"{subject} is at {_num(value)}{unit}, over {level_text}."
    return f"{subject} is over {level_text}."


def need_narration(
    *,
    source: str,
    host: str,
    service: str = "",
    metric: str = "",
    unit: str = "",
    value: float | None = None,
    crit: float | None = None,
    crit_date: str | None = None,
    confidence: str | None = None,
    history_days: float | None = None,
    since: datetime | None = None,
    sustained_fraction: float | None = None,
    window_hours: float | None = None,
    tz: tzinfo | None = None,
) -> str:
    """One-line narration of a need, filled only from the fields given (D-31).

    ``source`` is "trend", "sustained" or "failure". A failure with a
    ``service`` is a failing service, without one a DOWN host. ``metric`` is
    accepted for the caller's convenience; the subject is host plus service.
    """
    subject = f"{host} {service}".strip()
    if source == "trend":
        return _trend(subject, unit, value, crit, crit_date, confidence, history_days)
    if source == "sustained":
        return _sustained(subject, unit, value, crit, sustained_fraction, window_hours)
    since_clock = _since_clock(since, tz)
    tail = f" since {since_clock}" if since_clock else ""
    if service:
        return f"{host}: {service} is failing{tail}."
    return f"{host} has been DOWN{tail}." if since_clock else f"{host} has been DOWN."
