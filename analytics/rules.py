"""Need rules: tiers, identity, anti-flap tracking and triage carry-over (pure, no I/O).

Three need sources (D-07): a failure (host DOWN, or a monitored service or TCP
port CRIT), a trend that will reach its critical level, and a sustained or
already-breached reading. Tiers: failure tier comes from the operator's
criticality label (D-08), a per-service `service_criticality` entry overriding
the host's value for that service; trend tier is banded by days to critical
(D-09: <3 immediate, 3-20 urgent, >20 standard, >90 no need).

Reading of D-10 (flagged in research A4): the low-confidence cap applies to a
*predicted* date on a wear metric only, which is never immediate on its own and
is capped at urgent. An already-critical reading is an observation, not a
prediction, and stays immediate (it is raised by `sustained_need`, which is why
`trend_need` returns nothing for a series already at or above its critical
level: one row per series, no extra dedup).

Trend needs are raised only for the configured trend-need metric set (D-16);
any chart metric can still raise a sustained need. `need_id` is a hash so no
host or service name ever lands in a topic (D-14). A need is tombstoned only
after it has been absent for `RESOLVE_AFTER_CLEAN_CYCLES` consecutive cycles,
so a one-cycle flicker neither tombstones nor wipes triage. A triage override
is dropped when the computed tier becomes worse than it was at triage time and
the drop is reported for an `auto_reset` audit row (D-22, D-23). Service and TCP
port failure needs are suppressed for a host covered by an open incident (D-27);
the host-DOWN need is still raised (D-27 amended 2026-10-05, demo requirement: a
DOWN host shows in Needs next to its incident). Every need carries its
one-line narration (D-31).

Standard library only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, tzinfo

from analytics.fit import Fit
from analytics.narrate import need_narration

# Tier rank: lower is worse.
_TIER_RANK = {"immediate": 0, "urgent": 1, "standard": 2}
_CRITICALITY_TIER = {"critical": "immediate", "high": "urgent", "medium": "standard", "low": "standard"}

# Identical to scripts/mqtt_poller.py lines 767-768 (a test compares the patterns).
_CHOSEN_SERVICE_RE = re.compile(r"^(Systemd Service|Service) (?!Summary$)")
_TCP_PORT_SERVICE_RE = re.compile(r"^TCP Port \d+")

# D-14 / D-23: a need must be absent this many consecutive cycles before it is tombstoned.
RESOLVE_AFTER_CLEAN_CYCLES = 2


@dataclass(frozen=True)
class RuleParams:
    immediate_days: float = 3.0
    urgent_days: float = 20.0
    horizon_days: float = 90.0
    trend_need_metrics: frozenset[str] = frozenset()
    wear_metrics: frozenset[str] = frozenset()
    sustained_fraction: float = 0.8
    resolve_after_clean_cycles: int = RESOLVE_AFTER_CLEAN_CYCLES


@dataclass
class Need:
    id: str
    source: str  # "failure" | "trend" | "sustained"
    host: str
    service: str
    metric: str
    unit: str
    tier: str
    computed_tier: str
    since: datetime
    narration: str
    days_to_warn: float | None = None
    days_to_crit: float | None = None
    warn_date: str | None = None
    crit_date: str | None = None
    confidence: str | None = None
    history_days: float | None = None
    value: float | None = None
    warn: float | None = None
    crit: float | None = None
    sustained_fraction: float | None = None
    window_hours: float | None = None
    triage: dict | None = None
    generated_at: str | None = None
    tz: tzinfo | None = field(default=None, repr=False, compare=False)

    def renarrate(self) -> str:
        return need_narration(
            source=self.source,
            host=self.host,
            service=self.service,
            metric=self.metric,
            unit=self.unit,
            value=self.value,
            crit=self.crit,
            crit_date=self.crit_date,
            confidence=self.confidence,
            history_days=self.history_days,
            since=self.since,
            sustained_fraction=self.sustained_fraction,
            window_hours=self.window_hours,
            tz=self.tz,
        )

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "host": self.host,
            "service": self.service,
            "metric": self.metric,
            "unit": self.unit,
            "tier": self.tier,
            "computed_tier": self.computed_tier,
            "days_to_warn": self.days_to_warn,
            "days_to_crit": self.days_to_crit,
            "warn_date": self.warn_date,
            "crit_date": self.crit_date,
            "confidence": self.confidence,
            "history_days": self.history_days,
            "value": self.value,
            "warn": self.warn,
            "crit": self.crit,
            "sustained_fraction": self.sustained_fraction,
            "window_hours": self.window_hours,
            "since": self.since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "narration": self.narration,
            "triage": self.triage,
            "generated_at": self.generated_at,
        }


def need_id(source: str, host: str, service: str, metric: str) -> str:
    digest = hashlib.sha1(f"{source}|{host}|{service}|{metric}".encode()).hexdigest()
    return f"{source[0]}-{digest[:12]}"


def tier_from_criticality(criticality: object) -> str:
    return _CRITICALITY_TIER.get(criticality, "standard") if isinstance(criticality, str) else "standard"


def tier_from_days(days_to_crit: float, params: RuleParams) -> str | None:
    if days_to_crit > params.horizon_days:
        return None
    if days_to_crit < params.immediate_days:
        return "immediate"
    if days_to_crit <= params.urgent_days:
        return "urgent"
    return "standard"


def _make(source, host, service, metric, unit, tier, now, tz, **fields) -> Need:
    need = Need(
        id=need_id(source, host, service, metric),
        source=source,
        host=host,
        service=service,
        metric=metric,
        unit=unit,
        tier=tier,
        computed_tier=tier,
        since=now,
        narration="",
        tz=tz,
        **fields,
    )
    need.narration = need.renarrate()
    return need


def trend_need(
    host: str, service: str, metric: str, unit: str, fit: Fit, params: RuleParams, now: datetime, tz: tzinfo | None
) -> Need | None:
    if metric not in params.trend_need_metrics or fit.status != "trending":
        return None
    if fit.days_to_crit is None or fit.crit is None:
        return None
    if fit.last_value is not None and fit.last_value >= fit.crit:
        return None
    tier = tier_from_days(fit.days_to_crit, params)
    if tier is None:
        return None
    if tier == "immediate" and fit.confidence == "low" and metric in params.wear_metrics:
        tier = "urgent"
    return _make(
        "trend",
        host,
        service,
        metric,
        unit,
        tier,
        now,
        tz,
        days_to_warn=fit.days_to_warn,
        days_to_crit=fit.days_to_crit,
        warn_date=fit.warn_date,
        crit_date=fit.crit_date,
        confidence=fit.confidence,
        history_days=fit.history_days,
        value=fit.last_value,
        warn=fit.warn,
        crit=fit.crit,
    )


def sustained_need(
    host: str,
    service: str,
    metric: str,
    unit: str,
    hourly_values: list[float],
    latest: float | None,
    crit: float | None,
    warn: float | None,
    params: RuleParams,
    now: datetime,
    tz: tzinfo | None,
    window_hours: float,
) -> Need | None:
    if crit is None or (warn is not None and crit < warn) or not hourly_values:
        return None
    fraction = sum(1 for v in hourly_values if v >= crit) / len(hourly_values)
    already_critical = metric in params.trend_need_metrics and latest is not None and latest >= crit
    if fraction < params.sustained_fraction and not already_critical:
        return None
    return _make(
        "sustained",
        host,
        service,
        metric,
        unit,
        "immediate",
        now,
        tz,
        value=latest if latest is not None else hourly_values[-1],
        warn=warn,
        crit=crit,
        sustained_fraction=round(fraction, 2),
        window_hours=window_hours,
    )


def covered_hosts(open_incidents: dict[str, dict]) -> set[str]:
    """Hosts named by an open incident as root, confirmed down or not observable.

    Their service failure needs are suppressed (D-27); the host-DOWN need is not
    (D-27 amended 2026-10-05).
    """
    covered: set[str] = set()
    if not isinstance(open_incidents, dict):
        return covered
    for incident in open_incidents.values():
        if not isinstance(incident, dict):
            continue
        root = incident.get("root")
        if isinstance(root, str):
            covered.add(root)
        for key in ("confirmed_down", "not_observable"):
            members = incident.get(key)
            if isinstance(members, list):
                covered.update(m for m in members if isinstance(m, str))
    return covered


def _service_tier(node: dict, service: str) -> str:
    per_service = node.get("service_criticality")
    if isinstance(per_service, dict) and isinstance(per_service.get(service), str):
        return tier_from_criticality(per_service[service])
    return tier_from_criticality(node.get("criticality"))


def failure_needs(
    statuses: dict[str, dict],
    services: dict[str, list[dict]],
    topology_nodes: dict[str, dict],
    open_incidents: dict[str, dict],
    now: datetime,
    tz: tzinfo | None,
) -> list[Need]:
    needs: list[Need] = []
    covered = covered_hosts(open_incidents)
    hosts = set(statuses) | set(services) if isinstance(statuses, dict) and isinstance(services, dict) else set()
    for host in sorted(hosts, key=str):
        if not isinstance(host, str):
            continue
        node = topology_nodes.get(host) if isinstance(topology_nodes, dict) else None
        node = node if isinstance(node, dict) else {}
        status = statuses.get(host)
        if isinstance(status, dict) and status.get("host_state_raw") == "DOWN":
            needs.append(_make("failure", host, "", "", "", tier_from_criticality(node.get("criticality")), now, tz))
        if host in covered:
            # D-27 still applies to service needs; only the host-DOWN need above is
            # raised for covered hosts (reversal of 2026-10-05, quick 261005-dox).
            continue
        rows = services.get(host)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("state") != "CRIT":
                continue
            description = row.get("description")
            if not isinstance(description, str):
                continue
            if _CHOSEN_SERVICE_RE.match(description) or _TCP_PORT_SERVICE_RE.match(description):
                needs.append(_make("failure", host, description, "", "", _service_tier(node, description), now, tz))
    return needs


def carry_triage(prev: Need | None, new: Need) -> tuple[Need, dict | None]:
    """Apply the previous cycle's triage to a freshly computed need (D-22, D-23).

    Returns the need to publish and, when a triage was dropped because the
    computed tier became worse than at triage time, the auto_reset audit info.
    """
    new = replace(new, tier=new.computed_tier, triage=None)
    triage = prev.triage if prev is not None else None
    if not triage:
        return new, None
    at_set = triage.get("computed_tier_at_set")
    if _TIER_RANK.get(new.computed_tier, 2) < _TIER_RANK.get(at_set, 2):
        audit = {
            "action": "auto_reset",
            "tier_before": prev.tier,
            "tier_after": new.computed_tier,
            "computed_tier": new.computed_tier,
        }
        return new, audit
    tier = new.computed_tier if triage.get("action") == "cancel" else triage.get("tier", new.computed_tier)
    return replace(new, tier=tier, triage=triage), None


class NeedTracker:
    """Open needs (since, triage) plus one absent-cycle counter each; nothing else.

    The counter advances only when the need's source was evaluated (`evaluated_sources`),
    so failure needs clear after `RESOLVE_AFTER_CLEAN_CYCLES` absent fast ticks while
    trend and sustained needs still need that many absent successful slow cycles.
    """

    def __init__(self, params: RuleParams) -> None:
        self.params = params
        self._open: dict[str, tuple[Need, int]] = {}
        self.auto_resets: list[tuple[Need, dict]] = []

    def restore(self, needs: list[Need]) -> None:
        for need in needs:
            self._open[need.id] = (need, 0)

    def get(self, need_id: str) -> Need | None:
        entry = self._open.get(need_id)
        return entry[0] if entry else None

    def apply_override(self, need_id: str, triage: dict) -> None:
        entry = self._open.get(need_id)
        if entry is None:
            return
        need = entry[0]
        tier = need.computed_tier if triage.get("action") == "cancel" else triage.get("tier", need.computed_tier)
        self._open[need_id] = (replace(need, triage=triage, tier=tier), entry[1])

    def update(
        self,
        candidates: list[Need],
        now: datetime,
        evaluated_sources: frozenset[str] | set[str] | None = None,
    ) -> tuple[list[Need], list[str]]:
        """None means every source was evaluated; otherwise absent needs of other sources are kept unchanged."""
        self.auto_resets = []
        publish: list[Need] = []
        seen: set[str] = set()
        for candidate in candidates:
            seen.add(candidate.id)
            prev = self._open.get(candidate.id)
            need, audit = carry_triage(prev[0] if prev else None, candidate)
            if prev is not None:
                need = replace(need, since=prev[0].since)
                need.narration = need.renarrate()
            if audit is not None:
                self.auto_resets.append((need, audit))
            self._open[need.id] = (need, 0)
            publish.append(need)
        tombstones: list[str] = []
        for nid, (need, missed) in list(self._open.items()):
            if nid in seen:
                continue
            if evaluated_sources is not None and need.source not in evaluated_sources:
                publish.append(need)
                continue
            missed += 1
            if missed >= self.params.resolve_after_clean_cycles:
                del self._open[nid]
                tombstones.append(nid)
            else:
                self._open[nid] = (need, missed)
                publish.append(need)
        return publish, tombstones
