"""Cloud history writer: one site's history chunks from the cloud broker into ClickHouse.

Runs as `ANALYTICS_MODE=cloud-ingest` of the analytics container (D-02). It is
subscribe-only: it never publishes. It subscribes to
`app/<SITE_SEN>/<CMK_SITE_ID>/history/+` at QoS 1 over MQTT v5 with a persistent
session, and inserts each valid chunk's rows into `history.<table>`.

Why manual acknowledgement: a chunk is acknowledged only after its insert
attempt, so a crash mid-insert leaves it queued for redelivery on the stable
client id and session.

Why dedupe (D-03): delivery is at-least-once, so a chunk can arrive twice and
would double-count rollups. The `event_id` (MQTT v5 user property, else the
payload's `event_id`) of the last SEEN_MAX (topic, event_id) pairs is kept in
process; a restart forgets them.

Scope: history only. Events, incidents, triage audit and needs/forecasts stay
with the on-prem analytics container, whose outputs already reach the archive
through the bridge. One instance serves one (SEN, site) with its own
ClickHouse; the history tables carry no site or SEN column. An insert failure
is logged and the chunk is still acknowledged; the S3 archive is the replay
source.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Callable

from analytics.config import AnalyticsConfig
from analytics.history import (
    HISTORY_INGEST_TABLES,
    ClickHouseError,
    insert_history_rows,
)

_logger = logging.getLogger("analytics.ingest")

MAX_CHUNK_BYTES = 4 * 1024 * 1024
SEEN_MAX = 4096

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_TABLE_SEGMENTS = frozenset({"host_state", "service_state", "metrics"})

# Column -> kind, exactly the columns scripts/mqtt_poller.py build_history_rows emits.
# kinds: ts, str, int:<lo>:<hi>, num, num?
_ROW_SCHEMAS: dict[str, dict[str, str]] = {
    "host_state": {
        "ts": "ts",
        "host": "str",
        "folder": "str",
        "state": "int:0:2",
        "in_downtime": "int:0:1",
    },
    "service_state": {"ts": "ts", "host": "str", "service": "str", "state": "int:0:3"},
    "metrics": {
        "ts": "ts",
        "host": "str",
        "service": "str",
        "metric": "str",
        "value": "num",
        "warn": "num?",
        "crit": "num?",
    },
}


def ingest_prefix(sen: str, site_id: str) -> str:
    return f"app/{sen}/{site_id}/history/"


def _valid_value(kind: str, value: object) -> bool:
    if kind == "ts":
        return isinstance(value, str) and _TS_RE.fullmatch(value) is not None
    if kind == "str":
        return isinstance(value, str)
    if kind.startswith("int:"):
        _, lo, hi = kind.split(":")
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and int(lo) <= value <= int(hi)
        )
    if kind == "num?" and value is None:
        return True
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_rows(table: str, rows: object) -> list[dict]:
    """Return only the rows matching the exact column set and types of `table`."""
    schema = _ROW_SCHEMAS.get(table)
    if schema is None or not isinstance(rows, list):
        return []
    valid: list[dict] = []
    for row in rows:
        if (
            isinstance(row, dict)
            and set(row) == set(schema)
            and all(_valid_value(kind, row[col]) for col, kind in schema.items())
        ):
            valid.append(row)
    return valid


def _user_property_event_id(properties: object) -> str | None:
    for item in getattr(properties, "UserProperty", None) or []:
        try:
            key, value = item
        except (TypeError, ValueError):
            continue
        if key == "event_id" and isinstance(value, str) and value:
            return value
    return None


class HistoryIngest:
    def __init__(
        self,
        config: AnalyticsConfig,
        insert_fn: Callable[[AnalyticsConfig, str, list[dict]], None] = insert_history_rows,
    ) -> None:
        self.config = config
        self._insert_fn = insert_fn
        self._prefix = ingest_prefix(config.site_sen, config.cmk_site_id)
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()

    @property
    def subscription_filter(self) -> str:
        return self._prefix + "+"

    def _remember(self, key: tuple[str, str]) -> None:
        self._seen[key] = None
        while len(self._seen) > SEEN_MAX:
            self._seen.popitem(last=False)

    def handle(self, topic: str, payload: bytes, properties: object = None) -> None:
        if not topic.startswith(self._prefix):
            _logger.warning("Ignoring chunk on unexpected topic %r", topic)
            return
        segment = topic[len(self._prefix):]
        if segment not in _TABLE_SEGMENTS:
            _logger.warning("Ignoring chunk for unknown table segment %r", segment)
            return
        table = f"history.{segment}"
        if table not in HISTORY_INGEST_TABLES:
            return
        if len(payload) > MAX_CHUNK_BYTES:
            _logger.warning("Dropping oversized chunk on %s (%d bytes)", topic, len(payload))
            return
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            _logger.warning("Dropping chunk on %s: invalid JSON", topic)
            return
        if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
            _logger.warning("Dropping chunk on %s: not an object with a rows list", topic)
            return
        if body.get("table") != table:
            _logger.warning(
                "Dropping chunk on %s: payload table %r mismatches topic", topic, body.get("table")
            )
            return

        event_id = _user_property_event_id(properties)
        if event_id is None and isinstance(body.get("event_id"), str) and body["event_id"]:
            event_id = body["event_id"]
        key = (topic, event_id) if event_id is not None else None
        if key is None:
            _logger.debug("Chunk on %s has no event_id; inserting without dedupe", topic)
        elif key in self._seen:
            _logger.debug("Skipping duplicate chunk %s on %s", event_id, topic)
            return

        rows = validate_rows(segment, body["rows"])
        dropped = len(body["rows"]) - len(rows)
        if dropped:
            _logger.warning("Dropped %d invalid row(s) from chunk on %s", dropped, topic)
        if rows:
            try:
                self._insert_fn(self.config, table, rows)
            except (ClickHouseError, ValueError) as exc:
                _logger.warning("Insert into %s failed: %s", table, exc)
                return
        if key is not None:
            self._remember(key)


def build_ingest_client(ingest: HistoryIngest, config: AnalyticsConfig):
    """Create, authenticate and connect the MQTT v5 client with a persistent session.

    The v5 session expiry defaults to 0, which would discard queued chunks
    across a reconnect; a stable client id plus SessionExpiryInterval and
    clean_start=False keep them.
    """
    import paho.mqtt.client as mqtt
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties

    client_id = config.mqtt_client_id or f"analytics-ingest-{config.site_sen}-{config.cmk_site_id}"
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
        manual_ack=True,
    )
    client.username_pw_set(config.mqtt_username, config.mqtt_password)

    def on_connect(cl, userdata, flags, reason_code, properties=None):
        cl.subscribe(ingest.subscription_filter, qos=1)

    def on_message(cl, userdata, msg):
        try:
            ingest.handle(msg.topic, msg.payload, getattr(msg, "properties", None))
        except Exception:
            _logger.exception("Unhandled error ingesting chunk on %s", msg.topic)
        finally:
            cl.ack(msg.mid, msg.qos)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    connect_props = Properties(PacketTypes.CONNECT)
    connect_props.SessionExpiryInterval = config.mqtt_session_expiry_seconds
    client.connect(
        config.mqtt_host,
        config.mqtt_port,
        keepalive=30,
        clean_start=False,
        properties=connect_props,
    )
    return client


def run_ingest(config: AnalyticsConfig, stop_event: threading.Event, client_factory=None) -> int:
    ingest = HistoryIngest(config)
    factory = client_factory or build_ingest_client
    client = factory(ingest, config)
    client.loop_start()
    _logger.info("Cloud history ingest subscribed to %s (%r)", ingest.subscription_filter, config)
    try:
        stop_event.wait()
    finally:
        client.loop_stop()
        client.disconnect()
    return 0
