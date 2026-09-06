"""Live-poller smoke test proving PLR-01, PLR-04, PLR-05, PLR-06 and PLR-07 against a running stack.

This project's `tests/` suite is 100% mocked (see `tests/test_mqtt_poller.py`)
and cannot prove anything about a real Livestatus site or a real broker.
This script is the Phase 9 counterpart to `scripts/smoke_test_broker.py`:
deliberately standalone, run via
`uv run python scripts/smoke_test_poller.py` against a real deployment
host — not collected by pytest (no `test_*` function names, not under
`tests/`).

The sibling `scripts/mqtt_poller.py` module is loaded via
`importlib.util.spec_from_file_location` rather than duplicating its
Livestatus column probe or topic constants, so this script can never drift
from the poller's own contract.

Each check proves one requirement:
- `check_livestatus_columns` — resolves RESEARCH.md Open Question 1 and
  Assumptions A1-A3 (the live `hosts` table's actual column set).
- `check_device_status_retained` — Success Criterion 1 (PLR-03, PLR-08):
  at least one retained `lan/devices/{id}/status` payload matches the
  fixed contract.
- `check_topology_retained` — the payload half of PLR-01/PLR-04.
- `check_poller_liveness` — the positive half of Success Criterion 5
  (PLR-07): the poller's own heartbeat.
- `check_topology_quiet` — Success Criterion 3 (PLR-04): unrelated poll
  cycles produce no topology republish. Skipped by `--skip-slow`.
- `check_ghost_tombstone` — Success Criterion 4 (PLR-06): a host that
  disappeared while the poller was down gets tombstoned. Skipped by
  `--skip-restart-checks`.
- `check_lwt_offline` — the LWT half of Success Criterion 5 (PLR-07).
  Skipped by `--skip-restart-checks`.

The fifth success criterion (a real Checkmk host deletion) is not
exercised here — it needs a live Checkmk site to delete a host from, not
just a running broker — and is documented as a manual step in
`docs/Podman setup for checkmk, minio, mosquitto, worker.md`.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import pathlib
import shlex
import subprocess
import sys
import threading
import time
import types

import paho.mqtt.client as mqtt

GHOST_DEVICE_ID = "smoketest-ghost"

_VALID_STATES = {"OK", "WARN", "CRIT", "UNKNOWN", "DOWN"}
_DEVICE_STATUS_KEYS = {"id", "state", "in_downtime", "acknowledged", "device_type", "folder", "timestamp"}
_TOPOLOGY_NODE_KEYS = {"id", "parents", "device_type", "folder"}

_OPTIONAL_COLUMN_DEGRADATION = {
    "parents": "no topology links",
    "tags": 'device_type stays "unknown"',
    "filename": "folder stays empty",
    "scheduled_downtime_depth": "in_downtime stays False",
    "acknowledged": "acknowledged stays False",
    "worst_service_state": "overall state ignores service state",
}


def _load_poller_module() -> types.ModuleType:
    """Load scripts/mqtt_poller.py by path so this script reuses its contract, not a copy of it."""
    module_path = pathlib.Path(__file__).with_name("mqtt_poller.py")
    spec = importlib.util.spec_from_file_location("mqtt_poller", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec_module: mqtt_poller.py's @dataclass
    # decorators resolve string annotations (from __future__ import
    # annotations) via sys.modules[cls.__module__], which only works if the
    # module is already registered under that name at class-definition time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mqtt_poller = _load_poller_module()


def _wait_for_retained_payload(
    host: str, port: int, user: str, password: str, topic: str, timeout: float
) -> bytes | None:
    """Connect, subscribe to `topic`, and return its first retained payload, or None on timeout.

    Same idiom as scripts/smoke_test_broker.py's own `_wait_for_retained_payload`.
    """
    received = threading.Event()
    payloads: list[bytes] = []

    def on_message(client, userdata, msg):
        payloads.append(msg.payload)
        received.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    client.on_message = on_message
    try:
        client.connect(host, port)
        client.subscribe(topic, qos=1)
        client.loop_start()
        if received.wait(timeout=timeout):
            return payloads[0]
        return None
    finally:
        client.loop_stop()
        client.disconnect()


def _collect_retained(
    host: str, port: int, user: str, password: str, topic_filter: str, timeout: float
) -> dict[str, bytes]:
    """Connect, subscribe to a wildcard `topic_filter`, and collect every retained payload within `timeout`.

    Unlike `_wait_for_retained_payload`, this stays connected for the
    full window rather than returning on the first message, since a
    wildcard subscription can have many retained payloads delivered in
    quick succession right after SUBACK.
    """
    received: dict[str, bytes] = {}

    def on_message(client, userdata, msg):
        received[msg.topic] = msg.payload

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    client.on_message = on_message
    try:
        client.connect(host, port)
        client.subscribe(topic_filter, qos=1)
        client.loop_start()
        time.sleep(timeout)
    finally:
        client.loop_stop()
        client.disconnect()
    return received


def check_livestatus_columns(livestatus_host: str, livestatus_port: int, timeout: float) -> bool:
    """Resolve RESEARCH.md Open Question 1 / Assumptions A1-A3 against a live Checkmk site.

    FAILs only when a required column is missing; a missing optional
    column is a WARN naming the field that degrades, not a hard failure.
    """
    try:
        available = mqtt_poller.available_host_columns(livestatus_host, livestatus_port, timeout)
    except mqtt_poller.LivestatusError as exc:
        print(f"[FAIL] livestatus_columns: {exc}")
        return False

    ok = True
    degraded: list[str] = []
    for name in mqtt_poller.REQUIRED_HOST_COLUMNS:
        present = name in available
        ok = ok and present
        print(f"{'present' if present else 'MISSING'}: {name} (required)")
    for name in mqtt_poller.OPTIONAL_HOST_COLUMNS:
        present = name in available
        print(f"{'present' if present else 'missing'}: {name} (optional)")
        if not present:
            degraded.append(name)

    if not ok:
        print("[FAIL] livestatus_columns: a required column is missing")
        return False

    for name in degraded:
        reason = _OPTIONAL_COLUMN_DEGRADATION.get(name, "that field falls back to its safe default")
        print(f"[WARN] livestatus_columns: {name} missing -- {reason}")

    columns = mqtt_poller.select_host_columns(available)
    print(f"select_host_columns -> {columns}")
    print("[PASS] livestatus_columns")
    return True


def check_device_status_retained(host: str, tcp_port: int, user: str, password: str, timeout: float) -> bool:
    """Assert at least one retained lan/devices/{id}/status payload matches the fixed contract.

    Proves Success Criterion 1 (PLR-03, PLR-08).
    """
    try:
        payloads = _collect_retained(host, tcp_port, user, password, "lan/devices/+/status", timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] device_status_retained: {exc}")
        return False

    if not payloads:
        print("[FAIL] device_status_retained: no retained lan/devices/{id}/status payload found")
        return False

    matched = 0
    for payload in payloads.values():
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if not isinstance(data, dict) or set(data) != _DEVICE_STATUS_KEYS:
            continue
        if data.get("state") not in _VALID_STATES:
            continue
        if not isinstance(data.get("in_downtime"), bool) or not isinstance(data.get("acknowledged"), bool):
            continue
        try:
            datetime.datetime.fromisoformat(data["timestamp"])
        except (ValueError, TypeError):
            continue
        matched += 1

    if matched == 0:
        print(f"[FAIL] device_status_retained: none of {len(payloads)} retained payload(s) matched the fixed contract")
        return False
    print(f"[PASS] device_status_retained ({matched}/{len(payloads)} payload(s) matched)")
    return True


def check_topology_retained(host: str, tcp_port: int, user: str, password: str, timeout: float) -> bool:
    """Assert the retained lan/devices/topology payload matches the fixed contract.

    Proves the payload half of PLR-01/PLR-04.
    """
    try:
        payload = _wait_for_retained_payload(host, tcp_port, user, password, mqtt_poller.TOPIC_TOPOLOGY, timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] topology_retained: {exc}")
        return False

    if not payload:
        print("[FAIL] topology_retained: no retained lan/devices/topology payload found")
        return False
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"[FAIL] topology_retained: payload is not valid JSON ({exc})")
        return False
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        print("[FAIL] topology_retained: payload has no 'devices' list")
        return False
    try:
        datetime.datetime.fromisoformat(data.get("timestamp"))
    except (ValueError, TypeError) as exc:
        print(f"[FAIL] topology_retained: top-level timestamp unparseable ({exc})")
        return False
    for node in data["devices"]:
        if not isinstance(node, dict) or not _TOPOLOGY_NODE_KEYS <= set(node):
            print(f"[FAIL] topology_retained: node {node!r} missing required keys")
            return False
        if not isinstance(node["parents"], list):
            print(f"[FAIL] topology_retained: node {node['id']!r} parents is not a list")
            return False
    print(f"[PASS] topology_retained ({len(data['devices'])} device(s))")
    return True


def check_poller_liveness(
    host: str, tcp_port: int, user: str, password: str, timeout: float, poll_interval: float
) -> bool:
    """Assert lan/poller/status is online with a fresh last_poll heartbeat.

    Proves the positive half of Success Criterion 5 and RESEARCH.md
    Pitfall C's heartbeat requirement (PLR-07).
    """
    try:
        payload = _wait_for_retained_payload(host, tcp_port, user, password, mqtt_poller.TOPIC_POLLER_STATUS, timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] poller_liveness: {exc}")
        return False
    if not payload:
        print("[FAIL] poller_liveness: no retained lan/poller/status payload found")
        return False
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"[FAIL] poller_liveness: payload is not valid JSON ({exc})")
        return False
    if data.get("status") != "online":
        print(f"[FAIL] poller_liveness: status is {data.get('status')!r}, expected 'online'")
        return False
    last_poll = data.get("last_poll")
    try:
        last_poll_dt = datetime.datetime.fromisoformat(last_poll)
    except (ValueError, TypeError) as exc:
        print(f"[FAIL] poller_liveness: last_poll {last_poll!r} unparseable ({exc})")
        return False
    if last_poll_dt.tzinfo is None:
        last_poll_dt = last_poll_dt.replace(tzinfo=datetime.UTC)
    age = (datetime.datetime.now(datetime.UTC) - last_poll_dt).total_seconds()
    max_age = 3 * poll_interval
    if age > max_age:
        print(f"[FAIL] poller_liveness: last_poll is {age:.0f}s old, exceeds {max_age:.0f}s (3x poll interval)")
        return False
    print(f"[PASS] poller_liveness (last_poll {age:.0f}s ago)")
    return True


def check_topology_quiet(host: str, tcp_port: int, user: str, password: str, quiet_window: float) -> bool:
    """Assert no topology republish happens within `quiet_window` after the retained SUBACK message.

    Proves Success Criterion 3: unrelated poll cycles produce no
    topology republish (PLR-04).
    """
    received: list[bytes] = []
    first_seen = threading.Event()

    def on_message(client, userdata, msg):
        if not first_seen.is_set():
            first_seen.set()
            return  # discard the retained message delivered right after SUBACK
        received.append(msg.payload)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    client.on_message = on_message
    try:
        client.connect(host, tcp_port)
        client.subscribe(mqtt_poller.TOPIC_TOPOLOGY, qos=1)
        client.loop_start()
        time.sleep(quiet_window)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] topology_quiet: {exc}")
        return False
    finally:
        client.loop_stop()
        client.disconnect()

    if received:
        print(f"[FAIL] topology_quiet: {len(received)} unexpected topology republish(es) within {quiet_window}s")
        return False
    print(f"[PASS] topology_quiet (no republish within {quiet_window}s)")
    return True


def check_ghost_tombstone(
    host: str,
    tcp_port: int,
    user: str,
    password: str,
    restart_cmd: str,
    compose_dir: str,
    poll_interval: float,
    timeout: float,
) -> bool:
    """Seed a synthetic ghost node, restart the poller, and assert it gets tombstoned.

    Proves Success Criterion 4 (PLR-06) without touching Checkmk: this
    exercises exactly the "host disappeared while the poller was down"
    reconciliation path. Nothing needs restoring by hand afterward — the
    poller's own next cycle republishes correct topology.
    """
    try:
        payload = _wait_for_retained_payload(host, tcp_port, user, password, mqtt_poller.TOPIC_TOPOLOGY, timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] ghost_tombstone: {exc}")
        return False
    if not payload:
        print("[FAIL] ghost_tombstone: no retained lan/devices/topology payload to seed a ghost node into")
        return False
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"[FAIL] ghost_tombstone: existing topology payload is not valid JSON ({exc})")
        return False

    ghost_node = {"id": GHOST_DEVICE_ID, "parents": [], "device_type": "unknown", "folder": ""}
    devices = list(data.get("devices", [])) + [ghost_node]
    ghost_payload = json.dumps({"devices": devices, "timestamp": mqtt_poller.utc_now_iso()})

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    try:
        client.connect(host, tcp_port)
        client.loop_start()
        info = client.publish(mqtt_poller.TOPIC_TOPOLOGY, ghost_payload, qos=1, retain=True)
        info.wait_for_publish(timeout=timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] ghost_tombstone: could not seed ghost node ({exc})")
        return False
    finally:
        client.loop_stop()
        client.disconnect()

    result = subprocess.run(shlex.split(restart_cmd), cwd=compose_dir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"[FAIL] ghost_tombstone: restart command failed:\n{result.stdout}{result.stderr}".strip())
        return False

    attempt_interval = 5.0
    attempts = max(1, int((2 * poll_interval) // attempt_interval) + 1)
    ghost_gone = False
    for attempt in range(attempts):
        if attempt:
            time.sleep(attempt_interval)
        try:
            status_payload = _wait_for_retained_payload(
                host, tcp_port, user, password, mqtt_poller.device_status_topic(GHOST_DEVICE_ID), 2.0
            )
            history_payload = _wait_for_retained_payload(
                host, tcp_port, user, password, mqtt_poller.device_history_topic(GHOST_DEVICE_ID), 2.0
            )
            topology_payload = _wait_for_retained_payload(
                host, tcp_port, user, password, mqtt_poller.TOPIC_TOPOLOGY, 2.0
            )
        except (TimeoutError, OSError) as exc:
            print(f"[FAIL] ghost_tombstone: {exc}")
            return False

        topology_clear = True
        if topology_payload:
            try:
                topology_data = json.loads(topology_payload)
            except (json.JSONDecodeError, ValueError, TypeError):
                topology_data = {}
            topology_clear = all(
                node.get("id") != GHOST_DEVICE_ID for node in topology_data.get("devices", [])
            )

        if not status_payload and not history_payload and topology_clear:
            ghost_gone = True
            break

    if not ghost_gone:
        print("[FAIL] ghost_tombstone: smoketest-ghost was not tombstoned within two poll intervals")
        return False
    print("[PASS] ghost_tombstone")
    return True


def check_lwt_offline(
    host: str,
    tcp_port: int,
    user: str,
    password: str,
    kill_cmd: str,
    start_cmd: str,
    compose_dir: str,
    timeout: float,
) -> bool:
    """Kill the poller ungracefully and assert the LWT flips it offline, then bring it back.

    Proves the LWT half of Success Criterion 5 (PLR-07). Always attempts
    `start_cmd` once the offline assertion has been checked, regardless
    of outcome, so this check never leaves the poller down.
    """
    kill_result = subprocess.run(shlex.split(kill_cmd), cwd=compose_dir, capture_output=True, text=True, check=False)
    if kill_result.returncode != 0:
        print(f"[FAIL] lwt_offline: kill command failed:\n{kill_result.stdout}{kill_result.stderr}".strip())
        return False

    offline_confirmed = False
    try:
        payload = _wait_for_retained_payload(host, tcp_port, user, password, mqtt_poller.TOPIC_POLLER_STATUS, timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] lwt_offline: {exc}")
        payload = None
    if payload:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError, TypeError):
            data = {}
        offline_confirmed = data.get("status") == "offline"

    start_result = subprocess.run(shlex.split(start_cmd), cwd=compose_dir, capture_output=True, text=True, check=False)
    if start_result.returncode != 0:
        print(f"[WARN] lwt_offline: start command failed to bring the poller back:\n{start_result.stdout}{start_result.stderr}".strip())

    if not offline_confirmed:
        print(f"[FAIL] lwt_offline: lan/poller/status did not become offline within {timeout}s of the kill")
        return False

    online_confirmed = False
    for attempt in range(5):
        if attempt:
            time.sleep(3.0)
        try:
            payload = _wait_for_retained_payload(
                host, tcp_port, user, password, mqtt_poller.TOPIC_POLLER_STATUS, timeout
            )
        except (TimeoutError, OSError) as exc:
            print(f"[FAIL] lwt_offline: {exc}")
            return False
        if payload:
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError, TypeError):
                data = {}
            if data.get("status") == "online":
                online_confirmed = True
                break

    if not online_confirmed:
        print("[FAIL] lwt_offline: lan/poller/status did not return to online after restart")
        return False
    print("[PASS] lwt_offline")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test proving the Phase 9 poller's Livestatus column set "
        "and MQTT contract against a running stack.",
        epilog="In-container invocation (e.g. from the worker container): "
        "--host mosquitto --livestatus-host checkmk --skip-restart-checks "
        "(a sibling container cannot restart the poller service). The real "
        "Checkmk host-deletion tombstone test is a manual step documented in "
        "docs/Podman setup for checkmk, minio, mosquitto, worker.md.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--tcp-port", type=int, default=1883)
    parser.add_argument("--user", default="poller")
    parser.add_argument("--password", default="poller")
    parser.add_argument("--livestatus-host", default="localhost")
    parser.add_argument("--livestatus-port", type=int, default=6557)
    parser.add_argument("--poll-interval", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--quiet-window",
        type=float,
        default=None,
        help="Seconds to wait for an unexpected topology republish. Default: 2 * --poll-interval + 10.",
    )
    parser.add_argument("--skip-slow", action="store_true", help="Skip check_topology_quiet.")
    parser.add_argument(
        "--skip-restart-checks",
        action="store_true",
        help="Skip check_ghost_tombstone and check_lwt_offline (both restart/kill the poller).",
    )
    parser.add_argument("--restart-cmd", default="podman compose restart poller")
    parser.add_argument("--kill-cmd", default="podman compose kill -s KILL poller")
    parser.add_argument("--start-cmd", default="podman compose start poller")
    parser.add_argument("--compose-dir", default="deploy")
    args = parser.parse_args()

    quiet_window = args.quiet_window if args.quiet_window is not None else 2 * args.poll_interval + 10

    results: list[bool] = []
    results.append(check_livestatus_columns(args.livestatus_host, args.livestatus_port, args.timeout))
    results.append(
        check_device_status_retained(args.host, args.tcp_port, args.user, args.password, args.timeout)
    )
    results.append(check_topology_retained(args.host, args.tcp_port, args.user, args.password, args.timeout))
    results.append(
        check_poller_liveness(args.host, args.tcp_port, args.user, args.password, args.timeout, args.poll_interval)
    )

    if args.skip_slow:
        print("[SKIP] topology_quiet (--skip-slow)")
    else:
        results.append(check_topology_quiet(args.host, args.tcp_port, args.user, args.password, quiet_window))

    if args.skip_restart_checks:
        print("[SKIP] ghost_tombstone (--skip-restart-checks)")
        print("[SKIP] lwt_offline (--skip-restart-checks)")
    else:
        results.append(
            check_ghost_tombstone(
                args.host,
                args.tcp_port,
                args.user,
                args.password,
                args.restart_cmd,
                args.compose_dir,
                args.poll_interval,
                args.timeout,
            )
        )
        results.append(
            check_lwt_offline(
                args.host,
                args.tcp_port,
                args.user,
                args.password,
                args.kill_cmd,
                args.start_cmd,
                args.compose_dir,
                args.timeout,
            )
        )

    print(
        "[NOTE] The real-Checkmk host-deletion tombstone test (delete a host in the "
        "Checkmk UI and confirm it disappears from lan/devices/topology) is a manual "
        "step -- see the 'Manual tombstone test' section of "
        "docs/Podman setup for checkmk, minio, mosquitto, worker.md."
    )

    if all(results):
        print("[SUMMARY] all checks passed")
        return 0
    print("[SUMMARY] one or more checks failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
