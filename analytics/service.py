"""The analytics service: MQTT state, message routing, restore/reconcile, recorders and triage.

Inputs (all untrusted JSON from the broker) are subscribed with specific filters
only, never a bare site-wide wildcard, so the service never reads back its own
forecast/need/narration outputs except during the one-off restore window.

Inbound messages are handled on a dedicated worker thread, not in paho's
network callback: the handlers publish tombstones that wait for a broker
acknowledgement, and that acknowledgement is processed on the very thread the
callback would be blocking.

Every ClickHouse insert and every publish here is best-effort. They record
history and republish derived state; a failure degrades one message or one cycle
(logged) and must never take the service down. Retained outputs self-correct on
the next cycle.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import zoneinfo
from dataclasses import replace
from datetime import UTC, datetime, tzinfo

from analytics import history as _history
from analytics.config import (
    CONFIDENCE_HIGH_DAYS,
    CONFIDENCE_MEDIUM_DAYS,
    DROP_MIN_ABS,
    DROP_RANGE_FRACTION,
    FIT_BUCKET_HOURS,
    FIT_MIN_BUCKETS,
    FIT_MIN_SPAN_DAYS,
    RESOLVE_AFTER_CLEAN_CYCLES,
    SUSTAINED_FRACTION,
    WEAR_METRICS,
    AnalyticsConfig,
)
from analytics.fit import FitParams
from analytics.narrate import incident_narration
from analytics.publish import publish_retained_json, publish_tombstone
from analytics.recorder import EventRecorder, IncidentRecorder
from analytics.rules import Need, NeedTracker, RuleParams, tier_from_criticality
from analytics.topics import (
    NEED_ID_RE,
    TRIAGE_CMD_TOPIC,
    incident_narration_topic,
    need_status_topic,
    relative_topic,
    site_topic,
)
from analytics.triage import TriageCommandError, apply_triage, parse_triage_command

_logger = logging.getLogger("analytics.service")

# Relative input filters (subscribed under the site prefix, QoS 1).
INPUT_FILTERS = (
    "lan/devices/+/status",
    "lan/devices/+/services",
    "lan/devices/topology",
    "lan/events/recent",
    "lan/incidents/+/status",
    TRIAGE_CMD_TOPIC,
)
# Subscribed only for the restore window.
RESTORE_FILTERS = ("lan/needs/+/status", "lan/incidents/+/narration")
RESTORE_WINDOW_SECONDS = 5

_NEED_SOURCES = ("failure", "trend", "sustained")
_NEED_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_STOP = object()


def params_from_config(config: AnalyticsConfig) -> tuple[FitParams, RuleParams]:
    """Build the fit and rule parameter sets from the config and its fixed constants."""
    fit_params = FitParams(
        bucket_hours=FIT_BUCKET_HOURS,
        min_buckets=FIT_MIN_BUCKETS,
        min_span_days=FIT_MIN_SPAN_DAYS,
        r2_min=config.fit_r2_min,
        r2_high=config.fit_r2_high,
        min_rise_30d=config.fit_min_rise_30d,
        drop_min_abs=DROP_MIN_ABS,
        drop_range_fraction=DROP_RANGE_FRACTION,
        confidence_medium_days=CONFIDENCE_MEDIUM_DAYS,
        confidence_high_days=CONFIDENCE_HIGH_DAYS,
    )
    rule_params = RuleParams(
        immediate_days=config.tier_immediate_days,
        urgent_days=config.tier_urgent_days,
        horizon_days=config.need_horizon_days,
        trend_need_metrics=frozenset(config.trend_need_metrics),
        wear_metrics=WEAR_METRICS,
        sustained_fraction=SUSTAINED_FRACTION,
        resolve_after_clean_cycles=RESOLVE_AFTER_CLEAN_CYCLES,
    )
    return fit_params, rule_params


def _opt_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def need_from_payload(payload: object, tz: tzinfo | None) -> Need | None:
    """Rebuild a `Need` from one of this service's own retained payloads, or None if malformed."""
    if not isinstance(payload, dict):
        return None
    need_id = payload.get("id")
    source = payload.get("source")
    if not isinstance(need_id, str) or not NEED_ID_RE.match(need_id) or source not in _NEED_SOURCES:
        return None
    try:
        since = datetime.strptime(str(payload.get("since")), _NEED_TS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    tier = payload.get("tier")
    if not isinstance(tier, str):
        return None
    triage = payload.get("triage")
    return Need(
        id=need_id,
        source=source,
        host=str(payload.get("host") or ""),
        service=str(payload.get("service") or ""),
        metric=str(payload.get("metric") or ""),
        unit=str(payload.get("unit") or ""),
        tier=tier,
        computed_tier=_opt_str(payload.get("computed_tier")) or tier,
        since=since,
        narration=str(payload.get("narration") or ""),
        days_to_warn=_opt_float(payload.get("days_to_warn")),
        days_to_crit=_opt_float(payload.get("days_to_crit")),
        warn_date=_opt_str(payload.get("warn_date")),
        crit_date=_opt_str(payload.get("crit_date")),
        confidence=_opt_str(payload.get("confidence")),
        history_days=_opt_float(payload.get("history_days")),
        value=_opt_float(payload.get("value")),
        warn=_opt_float(payload.get("warn")),
        crit=_opt_float(payload.get("crit")),
        sustained_fraction=_opt_float(payload.get("sustained_fraction")),
        window_hours=_opt_float(payload.get("window_hours")),
        triage=triage if isinstance(triage, dict) else None,
        tz=tz,
    )


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_NEED_TS_FORMAT)


def _load_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def build_client(service: AnalyticsService):
    """Create, authenticate and connect the long-lived MQTT client.

    Clean session and no will: analytics publishes no status topic (staleness
    shows through `generated_at`), and subscriptions are re-issued in
    `on_connect` on every reconnect. Reconnect/backoff is left to paho.
    """
    import paho.mqtt.client as mqtt

    config = service.config
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
    client.on_connect = service.on_connect
    client.on_message = service.on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
    return client


class AnalyticsService:
    def __init__(
        self,
        config: AnalyticsConfig,
        client_factory=None,
        history_mod=_history,
        now_fn=None,
        sleep_fn=None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self.history = history_mod
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._sleep = sleep_fn or threading.Event().wait
        try:
            self.tz: tzinfo = zoneinfo.ZoneInfo(config.rollup_tz)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            _logger.warning("Unknown ROLLUP_TZ %r; narration uses UTC", config.rollup_tz)
            self.tz = UTC
        self.fit_params, self.rule_params = params_from_config(config)
        self.tracker = NeedTracker(self.rule_params)
        self.incident_recorder = IncidentRecorder(self.tz)
        self.event_recorder = EventRecorder()
        self.client = None
        self.lock = threading.RLock()
        # In-memory view of the inputs.
        self.statuses: dict[str, dict] = {}
        self.services: dict[str, list[dict]] = {}
        self.topology_nodes: dict[str, dict] = {}
        self.open_incidents: dict[str, dict] = {}
        # Last published narration content per incident (publish only on change).
        self._narration_sigs: dict[str, tuple] = {}
        # Trend/sustained needs from the last good cycle, re-fed when ClickHouse is down.
        self._slow_candidates: dict[str, Need] = {}
        self._forecast_hosts: set[str] = set()
        # Restore window state.
        self._restoring = False
        self._restored_needs: list[Need] = []
        self._retained_narrations: set[str] = set()
        # One insert warning per cycle.
        self._warned = False
        self._missing_tables: set[str] = set()
        # Async dispatch (set by start()); None means handle inline (tests).
        self._queue: queue.Queue | None = None
        self._worker: threading.Thread | None = None

    # --- MQTT wiring ------------------------------------------------------

    def start(self) -> None:
        """Seed from history, connect, restore state from retained topics, reconcile."""
        self._seed_from_history()
        self.client = (self._client_factory or build_client)(self)
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="analytics-dispatch", daemon=True)
        self._worker.start()
        self.client.loop_start()
        self.restore()
        self.reconcile()

    def stop(self) -> None:
        if self._queue is not None:
            self._queue.put(_STOP)
            if self._worker is not None:
                self._worker.join(timeout=10)
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()

    def on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        # Subscribed on every connect: a clean-session reconnect loses subscriptions.
        for topic_filter in INPUT_FILTERS:
            client.subscribe(site_topic(topic_filter), qos=1)

    def on_message(self, client, userdata, msg) -> None:
        if self._queue is not None:
            self._queue.put(msg)
        else:
            self.handle_message(msg)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                self.handle_message(item)
            except Exception:  # one bad message must not stop the dispatcher
                _logger.exception("Unhandled error handling an MQTT message")
            finally:
                self._queue.task_done()

    def _drain(self) -> None:
        if self._queue is not None:
            self._queue.join()

    def handle_message(self, msg) -> None:
        rel = relative_topic(msg.topic)
        if rel is None:
            return
        payload = msg.payload or b""
        if rel == TRIAGE_CMD_TOPIC:
            self._on_triage(payload, bool(msg.retain))
            return
        if rel == "lan/devices/topology":
            self._on_topology(payload)
            return
        if rel == "lan/events/recent":
            self._on_events(payload)
            return
        parts = rel.split("/")
        if len(parts) != 4 or parts[0] != "lan" or not parts[2]:
            return
        _, kind, ident, leaf = parts
        if kind == "devices" and leaf == "status":
            self._on_device(self.statuses, ident, payload, dict)
        elif kind == "devices" and leaf == "services":
            self._on_device(self.services, ident, payload, list)
        elif kind == "incidents" and leaf == "status":
            self._on_incident_status(ident, payload)
        elif self._restoring and kind == "needs" and leaf == "status":
            self._on_restored_need(ident, payload)
        elif self._restoring and kind == "incidents" and leaf == "narration" and payload:
            self._retained_narrations.add(ident)

    # --- state updates ----------------------------------------------------

    def _on_device(self, store: dict, device_id: str, payload: bytes, kind: type) -> None:
        with self.lock:
            if not payload:
                store.pop(device_id, None)
                return
            data = _load_json(payload)
            if isinstance(data, kind):
                store[device_id] = data

    def _on_topology(self, payload: bytes) -> None:
        data = _load_json(payload)
        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, list):
            return
        nodes = {
            node["id"]: node
            for node in devices
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        with self.lock:
            self.topology_nodes = nodes

    def _root_criticality(self, incident: dict) -> str | None:
        node = self.topology_nodes.get(incident.get("root"))
        value = node.get("criticality") if isinstance(node, dict) else None
        return value if isinstance(value, str) else None

    # --- recorders --------------------------------------------------------

    def _warn_once(self, what: str, exc: Exception) -> None:
        if self._warned:
            return
        self._warned = True
        hint = ""
        if self._missing_tables:
            hint = f" (missing tables {sorted(self._missing_tables)}: {self.history._MIGRATION_HINT})"
        _logger.warning("ClickHouse %s failed this cycle: %s%s", what, exc, hint)

    def _insert(self, table: str, rows: list[dict]) -> None:
        """Best-effort insert: history is a record, never a precondition for the live feed."""
        if not rows or not self.config.clickhouse_url:
            return
        try:
            self.history.insert_rows(self.config, table, rows)
        except (self.history.ClickHouseError, ValueError) as exc:
            self._warn_once(f"insert into {table}", exc)

    def _on_events(self, payload: bytes) -> None:
        with self.lock:
            rows = self.event_recorder.new_rows(payload)
        self._insert("history.events", rows)

    def _on_incident_status(self, incident_id: str, payload: bytes) -> None:
        now = self._now()
        if not payload:
            with self.lock:
                incident = self.open_incidents.pop(incident_id, None)
                criticality = self._root_criticality(incident) if incident else None
                row = self.incident_recorder.on_tombstone(incident_id, now, criticality)
                self._narration_sigs.pop(incident_id, None)
            if row is not None:
                self._insert("history.incidents", [row])
            publish_tombstone(self.client, incident_narration_topic(incident_id))
            return
        incident = _load_json(payload)
        if not isinstance(incident, dict):
            return
        with self.lock:
            self.open_incidents[incident_id] = incident
            criticality = self._root_criticality(incident)
            row = self.incident_recorder.on_status(incident_id, incident, now, criticality)
        if row is not None:
            self._insert("history.incidents", [row])
        self._publish_narration(incident_id, incident, criticality, now)

    def _publish_narration(
        self, incident_id: str, incident: dict, criticality: str | None, now: datetime
    ) -> None:
        narration = incident_narration(incident, criticality, now, self.tz)
        if narration is None:
            return
        worst = incident.get("worst_criticality")
        tier = tier_from_criticality(worst) if worst else None
        signature = (narration["headline"], tuple(narration["sentences"]), tier)
        with self.lock:
            if self._narration_sigs.get(incident_id) == signature:
                return
            self._narration_sigs[incident_id] = signature
        publish_retained_json(
            self.client,
            incident_narration_topic(incident_id),
            {
                "id": incident_id,
                "headline": narration["headline"],
                "sentences": narration["sentences"],
                "tier": tier,
                "generated_at": iso_utc(now),
            },
        )

    # --- triage -----------------------------------------------------------

    def publish_need(self, need: Need, now: datetime) -> None:
        stamped = replace(need, generated_at=iso_utc(now))
        publish_retained_json(self.client, need_status_topic(need.id), stamped.to_payload())

    def _on_triage(self, payload: bytes, retained: bool) -> None:
        if retained:
            # A retained command would be replayed on every restart; commands are live-only.
            return
        try:
            cmd = parse_triage_command(payload)
        except TriageCommandError as exc:
            _logger.warning("Ignoring triage command %s: %s", exc.command_id or "(no id)", exc.reason)
            return
        now = self._now()
        with self.lock:
            need = self.tracker.get(cmd.need_id)
            if need is None:
                _logger.warning("Ignoring triage command %s: unknown need %s", cmd.id, cmd.need_id)
                return
            triage, row = apply_triage(need, cmd, now)
        # Audit first, then republish: the record must exist before the change is visible.
        self._insert("history.need_triage", [row])
        with self.lock:
            self.tracker.apply_override(cmd.need_id, triage)
            updated = self.tracker.get(cmd.need_id)
        if updated is not None:
            self.publish_need(updated, now)

    # --- restore / reconcile ---------------------------------------------

    def _seed_from_history(self) -> None:
        if not self.config.clickhouse_url:
            _logger.warning("CLICKHOUSE_URL is unset: history, forecasts and trend needs are disabled")
            return
        self._missing_tables = self.history.missing_tables(self.config)
        if self._missing_tables:
            _logger.warning(
                "Analytics tables missing %s: %s", sorted(self._missing_tables), self.history._MIGRATION_HINT
            )
        try:
            self.incident_recorder.seed_open(self.history.fetch_open_incidents(self.config))
            self.event_recorder = EventRecorder(self.history.fetch_recent_event_keys(self.config))
        except (self.history.ClickHouseError, ValueError) as exc:
            _logger.warning("Could not seed recorders from history: %s", exc)

    def restore(self) -> None:
        """Rebuild needs from this service's own retained topics, once, at startup."""
        with self.lock:
            self._restoring = True
        for topic_filter in RESTORE_FILTERS:
            self.client.subscribe(site_topic(topic_filter), qos=1)
        self._sleep(RESTORE_WINDOW_SECONDS)
        for topic_filter in RESTORE_FILTERS:
            self.client.unsubscribe(site_topic(topic_filter))
        self._drain()
        with self.lock:
            self._restoring = False
            self.tracker.restore(self._restored_needs)
            self._slow_candidates = {n.id: n for n in self._restored_needs if n.source != "failure"}
            restored = len(self._restored_needs)
        _logger.info("Restored %d need(s) from retained topics", restored)

    def _on_restored_need(self, ident: str, payload: bytes) -> None:
        if not payload:
            return
        need = need_from_payload(_load_json(payload), self.tz)
        if need is not None and need.id == ident:
            with self.lock:
                self._restored_needs.append(need)

    def reconcile(self) -> None:
        """Close incidents stored open but no longer retained; clear orphaned narrations."""
        now = self._now()
        with self.lock:
            retained_ids = set(self.open_incidents)
            rows = self.incident_recorder.reconcile(retained_ids, now)
            orphans = sorted(self._retained_narrations - retained_ids)
        self._insert("history.incidents", rows)
        for incident_id in orphans:
            publish_tombstone(self.client, incident_narration_topic(incident_id))
