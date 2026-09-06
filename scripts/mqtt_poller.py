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

This plan (09-01) builds only the non-networked half of the poller:
environment-driven configuration, pure state/topology/bounded-log
helpers, and the Livestatus query layer that turns one `GET hosts` round
trip into typed `DeviceSnapshot` records. MQTT publishing itself is wired
up in a later plan.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

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
