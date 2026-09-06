"""Poller for the LAN monitoring dashboard: Livestatus-over-TCP -> per-device
retained MQTT topics (`lan/devices/{id}/status`, `lan/devices/topology`,
`lan/devices/{id}/history`, `lan/events/recent`).

Standalone script, not part of the installable `checkmk_wizard` package
--------------------------------------------------------------------
D-01 locks this as a standalone script rather than a module inside the
installable `checkmk_wizard` package: it must run independently of the
wizard and be deployable to a site where the wizard isn't needed or
installed. Do not import anything from `checkmk_wizard`, and do not wire
this into `[project.scripts]`.

Livestatus over TCP, not the local UNIX socket
-----------------------------------------------
This module talks to Livestatus over its TCP port (default 6557), the
same reasoning `src/checkmk_wizard/livestatus.py` documents: the poller
runs from a separate container/host than the Checkmk site itself, so it
must not require filesystem access to the `checkmk` container's own OMD
site (the container-boundary constraint this whole project is built
around).

Do not copy from `docs/src/mqtt_publisher_changes.py`
-------------------------------------------------------
That file is a documentation-only prototype using three now-deprecated
approaches this module must not repeat: the paho-mqtt v1 callback API
(no `CallbackAPIVersion.VERSION2`), Livestatus access over the local UNIX
socket instead of TCP, and a single full-blob retained topic instead of
this project's per-device topic contract.

MQTT client lifecycle and publish helpers below follow
`scripts/smoke_test_broker.py`'s live-tested paho-mqtt 2.1.0
`CallbackAPIVersion.VERSION2` idioms (this repo's own proven reference,
built and verified against a real deployed broker in Phase 8) rather
than generic docs.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import socket
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

DEFAULT_LIVESTATUS_PORT = 6557
DEFAULT_MQTT_PORT = 1883
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_HISTORY_MAX_ENTRIES = 20
DEFAULT_EVENTS_MAX_ENTRIES = 50
DEFAULT_RECONCILE_TIMEOUT_SECONDS = 5.0

TOPIC_TOPOLOGY = "lan/devices/topology"
TOPIC_EVENTS = "lan/events/recent"
TOPIC_POLLER_STATUS = "lan/poller/status"

UNKNOWN_DEVICE_TYPE = "unknown"

REQUIRED_HOST_COLUMNS = ("name", "state")
OPTIONAL_HOST_COLUMNS = (
    "scheduled_downtime_depth",
    "acknowledged",
    "worst_service_state",
    "parents",
    "tags",
    "filename",
)

# Standard Nagios plugin return codes, used unchanged by Checkmk/Livestatus
# for the `worst_service_state` column (verified: checkmk.com/werk/8003).
_SERVICE_STATE_NAMES = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}

# MQTT reserves `+`/`#` as wildcard characters and treats `/` as the
# topic-level separator (T-09-01 topic-injection guard).
_TOPIC_UNSAFE_CHARS = ("+", "#", "/")

_logger = logging.getLogger(__name__)


class LivestatusError(RuntimeError):
    """Raised for any Livestatus network failure or malformed response."""


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to `default` (with a warning) on a bad value.

    A typo in the compose file's environment block must never crash-loop
    the container — see PollerConfig.from_env().
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid integer for %s=%r; using default %r", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Float counterpart of `_env_int` — see its docstring."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning("Invalid float for %s=%r; using default %r", name, raw, default)
        return default


@dataclass
class PollerConfig:
    """Poller runtime settings, sourced entirely from environment variables (D-04)."""

    livestatus_host: str
    livestatus_port: int
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    poll_interval_seconds: int
    history_max_entries: int
    events_max_entries: int
    reconcile_timeout_seconds: float
    log_level: str

    def __repr__(self) -> str:
        # T-09-02: this object must be safe to log — never render the raw
        # MQTT password. Defined explicitly so @dataclass does not
        # generate a repr that would include it.
        return (
            "PollerConfig("
            f"livestatus_host={self.livestatus_host!r}, "
            f"livestatus_port={self.livestatus_port!r}, "
            f"mqtt_host={self.mqtt_host!r}, "
            f"mqtt_port={self.mqtt_port!r}, "
            f"mqtt_username={self.mqtt_username!r}, "
            "mqtt_password='***', "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, "
            f"history_max_entries={self.history_max_entries!r}, "
            f"events_max_entries={self.events_max_entries!r}, "
            f"reconcile_timeout_seconds={self.reconcile_timeout_seconds!r}, "
            f"log_level={self.log_level!r})"
        )

    @classmethod
    def from_env(cls) -> PollerConfig:
        return cls(
            livestatus_host=os.environ.get("LIVESTATUS_HOST", "checkmk"),
            livestatus_port=_env_int("LIVESTATUS_PORT", DEFAULT_LIVESTATUS_PORT),
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=_env_int("MQTT_PORT", DEFAULT_MQTT_PORT),
            mqtt_username=os.environ.get("MQTT_USERNAME", "poller"),
            mqtt_password=os.environ.get("MQTT_PASSWORD", "poller"),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
            history_max_entries=_env_int("HISTORY_MAX_ENTRIES", DEFAULT_HISTORY_MAX_ENTRIES),
            events_max_entries=_env_int("EVENTS_MAX_ENTRIES", DEFAULT_EVENTS_MAX_ENTRIES),
            reconcile_timeout_seconds=_env_float(
                "RECONCILE_TIMEOUT_SECONDS", DEFAULT_RECONCILE_TIMEOUT_SECONDS
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )


@dataclass
class DeviceSnapshot:
    """One device's current state, as derived from a single Livestatus `hosts` row."""

    id: str
    state: str
    # Field names locked by D-07, mirroring Livestatus's own column
    # naming so the payload traces back cleanly to source columns:
    # in_downtime <- scheduled_downtime_depth > 0, acknowledged <- acknowledged.
    in_downtime: bool
    acknowledged: bool
    device_type: str
    folder: str
    parents: list[str] = field(default_factory=list)


def configure_logging(level: str) -> None:
    """Wire up `logging.basicConfig`. Called by `main()`; never at import time."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def device_status_topic(device_id: str) -> str:
    return f"lan/devices/{device_id}/status"


def device_history_topic(device_id: str) -> str:
    return f"lan/devices/{device_id}/history"


def is_publishable_device_id(device_id: str) -> bool:
    """Reject any device id that would corrupt the MQTT topic hierarchy if interpolated.

    Livestatus reports every host known to Checkmk, including hosts
    created outside this project's own wizard (whose onboarding flow
    already validates hostnames via `_HOSTNAME_RE`) — e.g. via the
    Checkmk UI directly, or `bulk_create_hosts`. Any such name could
    contain `/`, `+`, `#` or control characters, so this check must run
    on every host name Livestatus returns, not just wizard-onboarded
    ones (T-09-01).
    """
    if not device_id or not device_id.strip():
        return False
    if any(ch in device_id for ch in _TOPIC_UNSAFE_CHARS):
        return False
    return not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in device_id)


def compute_overall_state(host_state: int, worst_service_state: int) -> str:
    """Worst-of aggregation (D-08): host DOWN/UNREACHABLE always wins outright."""
    if host_state != 0:  # 1=DOWN, 2=UNREACHABLE (src/checkmk_wizard/livestatus.py convention)
        return "DOWN"
    return _SERVICE_STATE_NAMES.get(worst_service_state, "UNKNOWN")


def append_bounded(entries: list[dict], entry: dict, max_entries: int) -> list[dict]:
    """Return a new bounded list with `entry` appended, never mutating `entries`."""
    return (entries + [entry])[-max_entries:]


def topology_nodes(snapshots: list[DeviceSnapshot]) -> list[dict]:
    return [
        {
            "id": snapshot.id,
            "parents": list(snapshot.parents),
            "device_type": snapshot.device_type,
            "folder": snapshot.folder,
        }
        for snapshot in snapshots
    ]


def topology_signature(nodes: list[dict]) -> tuple:
    """Order-independent signature used to decide whether topology actually changed."""
    return tuple(
        sorted(
            (node["id"], tuple(sorted(node["parents"])), node["device_type"], node["folder"])
            for node in nodes
        )
    )


def derive_folder(filename: str) -> str:
    """Derive a folder path from a Livestatus `filename` (WATO config path).

    Takes the path segment(s) after the `wato/` segment and drops the
    trailing `hosts.mk`. Returns "" when there is no `wato/` segment, or
    the host sits directly in the WATO root.
    """
    parts = filename.split("/")
    try:
        wato_index = parts.index("wato")
    except ValueError:
        return ""
    segment_parts = parts[wato_index + 1 :]
    if segment_parts and segment_parts[-1] == "hosts.mk":
        segment_parts = segment_parts[:-1]
    return "/".join(segment_parts)


def extract_device_type(tags: dict) -> str:
    """Read a device-type tag defensively; the tag itself doesn't exist until Phase 10.

    Until then, every host is untagged and the safe "unknown" default is
    the normal, expected case, not an error condition.
    """
    if "device_type" in tags:
        return tags["device_type"]
    if "tag_device_type" in tags:
        return tags["tag_device_type"]
    return UNKNOWN_DEVICE_TYPE


def _livestatus_request(host: str, port: int, query: str, timeout: float) -> str:
    """Send one LQL query and return the raw response body.

    Every Livestatus network failure funnels through this one choke
    point and is normalized into `LivestatusError` exactly once (same
    pattern as `CheckmkClient._request` in `src/checkmk_wizard/api.py`),
    so call sites never need their own try/except for connectivity.
    Extends `src/checkmk_wizard/livestatus.py`'s exact transport idiom;
    only the LQL headers differ.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(query.encode())
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except (TimeoutError, OSError) as exc:
        raise LivestatusError(f"Livestatus request to {host}:{port} failed: {exc}") from exc
    return b"".join(chunks).decode(errors="replace")


def available_host_columns(host: str, port: int, timeout: float) -> set[str]:
    """Return the column names the live site's `hosts` table actually exposes.

    Checkmk publishes no static column reference for the `hosts` table;
    the documented way to get ground truth is a live `GET columns` query
    (docs.checkmk.com/latest/en/livestatus_references.html) — resolves
    09-RESEARCH.md Open Question 1 / Assumptions A1-A3.
    """
    query = "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    body = _livestatus_request(host, port, query, timeout)
    if not body.strip():
        return set()
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed columns response from {host}:{port}: {exc}") from exc
    return {row[0] for row in rows}


def select_host_columns(available: set[str]) -> list[str]:
    """Build the column list to request, degrading unverified optional columns gracefully.

    Every name in REQUIRED_HOST_COLUMNS must be present or the query
    cannot proceed at all. Optional columns (parents/tags/filename etc.)
    are included only when the live site actually exposes them; an
    absent optional column is a logged degradation, not a hard failure.
    """
    missing = [name for name in REQUIRED_HOST_COLUMNS if name not in available]
    if missing:
        raise LivestatusError(
            f"Livestatus hosts table is missing required column(s): {', '.join(missing)}"
        )
    columns = list(REQUIRED_HOST_COLUMNS)
    for name in OPTIONAL_HOST_COLUMNS:
        if name in available:
            columns.append(name)
        else:
            _logger.warning(
                "Livestatus hosts table does not expose optional column %r; "
                "degrading to a safe default for that field",
                name,
            )
    return columns


def build_hosts_query(columns: list[str]) -> str:
    return f"GET hosts\nColumns: {' '.join(columns)}\nOutputFormat: json\n\n"


def query_devices(host: str, port: int, columns: list[str], timeout: float) -> list[DeviceSnapshot]:
    """Run one `GET hosts` round trip and parse it into typed DeviceSnapshot records.

    Defensive by design (T-09-03): a malformed response, a topic-unsafe
    host name, or a non-numeric state field skips that one row (or the
    whole cycle, for a fully malformed response) rather than crashing
    the poll loop.
    """
    body = _livestatus_request(host, port, build_hosts_query(columns), timeout)
    if not body.strip():
        return []
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed hosts response from {host}:{port}: {exc}") from exc

    index = {name: position for position, name in enumerate(columns)}
    snapshots: list[DeviceSnapshot] = []
    for row in rows:
        try:
            name = row[index["name"]]
        except (IndexError, TypeError):
            _logger.warning("Skipping malformed hosts row: %r", row)
            continue
        if not is_publishable_device_id(name):
            _logger.warning("Skipping host %r: not publishable as an MQTT topic segment", name)
            continue
        try:
            host_state = int(row[index["state"]])
        except (IndexError, TypeError, ValueError):
            _logger.warning("Skipping host %r: non-numeric state", name)
            continue

        worst_service_state = 0
        if "worst_service_state" in index:
            try:
                worst_service_state = int(row[index["worst_service_state"]])
            except (TypeError, ValueError):
                _logger.warning("Skipping host %r: non-numeric worst_service_state", name)
                continue

        downtime_depth = 0
        if "scheduled_downtime_depth" in index:
            try:
                downtime_depth = int(row[index["scheduled_downtime_depth"]])
            except (TypeError, ValueError):
                downtime_depth = 0

        acknowledged = bool(row[index["acknowledged"]]) if "acknowledged" in index else False

        raw_parents = row[index["parents"]] if "parents" in index else None
        parents = list(raw_parents) if isinstance(raw_parents, list) else []

        raw_tags = row[index["tags"]] if "tags" in index else None
        tags = raw_tags if isinstance(raw_tags, dict) else {}

        folder = derive_folder(row[index["filename"]]) if "filename" in index else ""

        snapshots.append(
            DeviceSnapshot(
                id=name,
                state=compute_overall_state(host_state, worst_service_state),
                in_downtime=downtime_depth > 0,
                acknowledged=acknowledged,
                device_type=extract_device_type(tags),
                folder=folder,
                parents=parents,
            )
        )
    return snapshots


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601, matching wizard.py's `datetime.UTC` convention."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def build_mqtt_client(config: PollerConfig) -> mqtt.Client:
    """Construct, authenticate and connect the poller's long-lived MQTT client.

    `will_set()` is called before `connect()` because paho-mqtt's own
    docstring states it has no effect otherwise -- this ordering is
    load-bearing, not stylistic. Reconnect/backoff is deliberately left
    to the library (`reconnect_delay_set` + `loop_start`), not
    hand-rolled, per RESEARCH.md's "Don't Hand-Roll" guidance.
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
    client.will_set(
        TOPIC_POLLER_STATUS,
        payload=json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    def on_connect(client, userdata, flags, reason_code, properties=None):
        # Birth message: last_poll is None until the first cycle completes.
        publish_poller_status(client, since=utc_now_iso(), last_poll=None, device_count=0)

    client.on_connect = on_connect
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
    client.loop_start()
    return client


def _publish_json(client: mqtt.Client, topic: str, payload: object, qos: int, retain: bool) -> None:
    """Serialize `payload` as JSON and publish, one choke point for every publish helper.

    Mirrors `CheckmkClient._request()`'s pattern (src/checkmk_wizard/api.py):
    every publish goes through here so a transient broker hiccup
    (`TimeoutError`/`OSError`) degrades exactly one publish rather than
    killing the poll loop (T-09-03).

    Continuous vs. change-triggered QoS rule (RESEARCH.md's resolved
    table): the every-cycle status topic uses QoS 0 (self-correcting by
    the next cycle), every change-triggered topic uses QoS 1. Callers
    choose `qos`; this function does not second-guess it.
    """
    try:
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)


def publish_device_status(client: mqtt.Client, snapshot: DeviceSnapshot, timestamp: str) -> None:
    """Publish one device's current status. QoS 0: republished every cycle from live data."""
    payload = {
        "id": snapshot.id,
        "state": snapshot.state,
        "in_downtime": snapshot.in_downtime,
        "acknowledged": snapshot.acknowledged,
        "device_type": snapshot.device_type,
        "folder": snapshot.folder,
        "timestamp": timestamp,
    }
    _publish_json(client, device_status_topic(snapshot.id), payload, qos=0, retain=True)


def publish_topology(client: mqtt.Client, nodes: list[dict], timestamp: str) -> None:
    """Publish the full device topology. QoS 1: only republished when it actually changes."""
    payload = {"devices": nodes, "timestamp": timestamp}
    _publish_json(client, TOPIC_TOPOLOGY, payload, qos=1, retain=True)


def publish_history(client: mqtt.Client, device_id: str, entries: list[dict]) -> None:
    """Publish one device's full bounded transition history (already truncated by the caller)."""
    _publish_json(client, device_history_topic(device_id), entries, qos=1, retain=True)


def publish_events(client: mqtt.Client, entries: list[dict]) -> None:
    """Publish the full bounded global events feed (already truncated by the caller)."""
    _publish_json(client, TOPIC_EVENTS, entries, qos=1, retain=True)


def publish_tombstone(client: mqtt.Client, device_id: str) -> None:
    """Clear a removed device's retained status and history topics.

    A zero-length retained payload is MQTT's own defined "clear this
    retained topic" semantic -- the same mechanism as
    `scripts/smoke_test_broker.py::_cleanup`, already proven against the
    real deployed broker. Uses `wait_for_publish` like that function does,
    since a tombstone matters more than most publishes: the removed
    device must not linger as a stale retained message.
    """
    for topic in (device_status_topic(device_id), device_history_topic(device_id)):
        try:
            info = client.publish(topic, payload=None, retain=True, qos=1)
            info.wait_for_publish(timeout=5)
        except (TimeoutError, OSError) as exc:
            _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)


def publish_poller_status(
    client: mqtt.Client, since: str, last_poll: str | None, device_count: int
) -> None:
    """Publish the poller's liveness status: birth (`last_poll=None`) or a per-cycle heartbeat.

    MQTT's LWT only fires on an ungraceful TCP disconnect, so a poller
    whose poll loop has stalled while its network thread keeps the
    socket alive would otherwise read as permanently "online" forever.
    The refreshed `last_poll` published every cycle is what lets Phase
    11's DASH-04 staleness check ("now - last_poll > threshold") catch
    that condition (RESEARCH.md Pitfall C).
    """
    payload = {
        "status": "online",
        "since": since,
        "last_poll": last_poll,
        "device_count": device_count,
    }
    _publish_json(client, TOPIC_POLLER_STATUS, payload, qos=1, retain=True)
