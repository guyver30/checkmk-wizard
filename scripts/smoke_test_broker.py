"""Live-broker smoke test proving BRK-01, BRK-02 and BRK-03 against a running Mosquitto.

This project's `tests/` suite is 100% mocked and never touches live
infrastructure (see `tests/test_*.py`), so it cannot prove any of the three
broker-hardening requirements this phase delivers. This script is
deliberately standalone, run via `uv run python scripts/smoke_test_broker.py`
against a real deployment host — not collected by pytest (no `test_*`
function names, not under `tests/`).

Each check proves one requirement:
- `check_poller_publish` — the poller's authenticated write path on plain
  MQTT 1883 works (D-05: 1883 is no longer anonymous).
- `check_ws_subscribe` — the WebSockets listener is reachable and distinct
  from 1883, and a read-only client can subscribe (BRK-01, read half of
  BRK-03).
- `check_ws_publish_denied` — the WS read-only user cannot publish
  (write half of BRK-03). This check is structured around a subtlety in
  MQTT 3.1.1 (the default protocol version both Mosquitto and paho-mqtt
  negotiate unless told otherwise): Mosquitto still sends a normal PUBACK
  to a publisher whose message the ACL silently drops server-side — MQTT
  3.1.1's PUBACK carries no reason-code field at all (that's an MQTT 5
  addition). Checking the publisher's own return value would therefore
  report "success" for a publish the broker actually rejected, a false
  PASS for exactly the property this phase exists to prove. The only
  reliable check is a bounded wait on an INDEPENDENT, privileged
  subscriber that should never receive the message.
- `check_persistence_across_restart` — a retained message survives a
  broker restart (BRK-02), skipped via `--skip-restart` for callers (e.g.
  the worker container) that must not restart a sibling service.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

SMOKETEST_SEED_TOPIC = "lan/smoketest/seed"
SMOKETEST_DENY_TOPIC = "lan/smoketest/deny-check"


def check_poller_publish(
    host: str,
    tcp_port: int,
    user: str,
    password: str,
    seed: str,
    timeout: float,
) -> bool:
    """Publish a retained seed value as the poller user over plain MQTT.

    Proves the poller's authenticated write path works (D-05: 1883 is no
    longer anonymous). A non-success CONNACK reason code means the
    password file or the config mount path is wrong, not a transient
    network issue.
    """
    connected = threading.Event()
    reason_codes: list[object] = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        reason_codes.append(reason_code)
        connected.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    client.on_connect = on_connect
    try:
        client.connect(host, tcp_port)
        client.loop_start()
        if not connected.wait(timeout=timeout):
            print(f"[FAIL] poller_publish: no CONNACK within {timeout}s")
            return False
        if reason_codes[0] != 0:
            print(f"[FAIL] poller_publish: CONNACK reason code {reason_codes[0]!r} (auth/config likely wrong)")
            return False
        info = client.publish(SMOKETEST_SEED_TOPIC, seed, qos=1, retain=True)
        info.wait_for_publish(timeout=timeout)
        if not info.is_published():
            print(f"[FAIL] poller_publish: publish not confirmed within {timeout}s")
            return False
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] poller_publish: {exc}")
        return False
    finally:
        client.loop_stop()
        client.disconnect()
    print("[PASS] poller_publish")
    return True


def check_ws_subscribe(
    host: str,
    ws_port: int,
    user: str,
    password: str,
    seed: str,
    timeout: float,
) -> bool:
    """Subscribe over the WebSockets listener and confirm the retained seed round-trips.

    Proves BRK-01 (the WebSockets listener is reachable and distinct from
    1883) and the read half of BRK-03. Uses a raw `Client` with
    `loop_start()` and a bounded `threading.Event` rather than the
    one-shot `paho.mqtt.subscribe` helpers, which have no timeout
    parameter and would hang forever if the retained message were absent.
    """
    received = threading.Event()
    payloads: list[bytes] = []

    def on_message(client, userdata, msg):
        payloads.append(msg.payload)
        received.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.username_pw_set(user, password)
    client.on_message = on_message
    try:
        client.connect(host, ws_port)
        client.subscribe(f"{SMOKETEST_SEED_TOPIC.rsplit('/', 1)[0]}/#")
        client.loop_start()
        if not received.wait(timeout=timeout):
            print(f"[FAIL] ws_subscribe: no retained message within {timeout}s")
            return False
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] ws_subscribe: {exc}")
        return False
    finally:
        client.loop_stop()
        client.disconnect()

    if payloads[0].decode() != seed:
        print(f"[FAIL] ws_subscribe: payload mismatch (expected {seed!r}, got {payloads[0]!r})")
        return False
    print("[PASS] ws_subscribe")
    return True


def check_ws_publish_denied(
    host: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    ws_user: str,
    ws_password: str,
    timeout: float,
) -> bool:
    """Assert a wsreader publish never reaches an independent privileged subscriber.

    The security-critical check (T-08-11). Deliberately does NOT inspect
    the publisher's return code / PUBACK — see the module docstring for
    why that would be a false PASS under MQTT 3.1.1. The assertion is
    made entirely from a second, independently-connected subscriber
    authenticated as the full-access poller user.
    """
    received = threading.Event()

    def on_message(client, userdata, msg):
        received.set()

    privileged = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    privileged.username_pw_set(poller_user, poller_password)
    privileged.on_message = on_message
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    publisher.username_pw_set(ws_user, ws_password)
    try:
        privileged.connect(host, tcp_port)
        privileged.subscribe(SMOKETEST_DENY_TOPIC)
        privileged.loop_start()

        publisher.connect(host, ws_port)
        publisher.loop_start()
        # Return code/PUBACK from this publish is intentionally never
        # checked — MQTT 3.1.1 acknowledges it regardless of ACL outcome.
        publisher.publish(SMOKETEST_DENY_TOPIC, "should-never-arrive", qos=1, retain=True)
        arrived = received.wait(timeout=timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[FAIL] ws_publish_denied: {exc}")
        return False
    finally:
        publisher.loop_stop()
        publisher.disconnect()
        privileged.loop_stop()
        privileged.disconnect()

    if arrived:
        print("[FAIL] ws_publish_denied: wsreader publish reached the privileged subscriber (ACL not enforced)")
        return False
    print("[PASS] ws_publish_denied")
    return True


def _wait_for_retained_payload(
    host: str,
    port: int,
    user: str,
    password: str,
    topic: str,
    timeout: float,
) -> bytes | None:
    """Connect, subscribe to `topic`, and return its first retained payload, or None on timeout.

    Extracted to its own function (rather than defined inline inside a
    retry loop) so the `on_message` closure isn't a loop-variable capture
    ruff would flag as unsafe (B023).
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
        client.subscribe(topic)
        client.loop_start()
        if received.wait(timeout=timeout):
            return payloads[0]
        return None
    finally:
        client.loop_stop()
        client.disconnect()


def check_persistence_across_restart(
    host: str,
    tcp_port: int,
    user: str,
    password: str,
    seed: str,
    timeout: float,
    restart_cmd: str,
    compose_dir: str,
) -> bool:
    """Restart the broker and confirm the retained seed still survives (BRK-02).

    Follows `site.py`'s subprocess convention: `check=False` plus manual
    returncode inspection, never a raise-on-nonzero call or a shell
    string. After the restart, reconnects with a bounded retry loop
    since the broker needs a moment to rebind its listeners.
    """
    result = subprocess.run(
        shlex.split(restart_cmd),
        cwd=compose_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "[FAIL] persistence_across_restart: restart command failed:\n"
            f"{result.stdout}{result.stderr}".strip()
        )
        return False

    seed_matched = False
    last_error: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        try:
            payload = _wait_for_retained_payload(host, tcp_port, user, password, SMOKETEST_SEED_TOPIC, timeout)
        except (TimeoutError, OSError) as exc:
            last_error = exc
            continue
        seed_matched = payload is not None and payload.decode() == seed
        if seed_matched:
            break

    if not seed_matched:
        reason = f" ({last_error})" if last_error else ""
        print(f"[FAIL] persistence_across_restart: retained seed did not survive the restart{reason}")
        return False
    print("[PASS] persistence_across_restart")
    return True


def _cleanup(host: str, tcp_port: int, user: str, password: str, timeout: float) -> None:
    """Clear the retained smoke-test topics so no ghosts leak into lan/#.

    Run from a `finally` block regardless of check outcome. A cleanup
    failure is reported as a warning only — it never flips the overall
    pass/fail result.
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    try:
        client.connect(host, tcp_port)
        client.loop_start()
        for topic in (SMOKETEST_SEED_TOPIC, SMOKETEST_DENY_TOPIC):
            info = client.publish(topic, payload=None, retain=True)
            info.wait_for_publish(timeout=timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[WARN] cleanup: could not clear retained smoke-test topics: {exc}")
    finally:
        client.loop_stop()
        client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke test proving BRK-01, BRK-02 and BRK-03 against a running Mosquitto broker.",
        epilog="In-container invocation (e.g. from the worker container): "
        "--host mosquitto --ws-port 9001 --skip-restart "
        "(the worker container cannot restart its sibling broker).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--tcp-port", type=int, default=1883)
    parser.add_argument("--ws-port", type=int, default=9002)
    parser.add_argument("--poller-user", default="poller")
    parser.add_argument("--poller-password", default="poller")
    parser.add_argument("--ws-user", default="wsreader")
    parser.add_argument("--ws-password", default="wsreader")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--restart-cmd", default="podman compose restart mosquitto")
    parser.add_argument("--compose-dir", default="deploy")
    args = parser.parse_args()

    seed = uuid.uuid4().hex
    results: list[bool] = []
    try:
        results.append(
            check_poller_publish(args.host, args.tcp_port, args.poller_user, args.poller_password, seed, args.timeout)
        )
        results.append(
            check_ws_subscribe(args.host, args.ws_port, args.ws_user, args.ws_password, seed, args.timeout)
        )
        results.append(
            check_ws_publish_denied(
                args.host,
                args.tcp_port,
                args.ws_port,
                args.poller_user,
                args.poller_password,
                args.ws_user,
                args.ws_password,
                args.timeout,
            )
        )
        if args.skip_restart:
            print("[SKIP] persistence_across_restart (--skip-restart)")
        else:
            results.append(
                check_persistence_across_restart(
                    args.host,
                    args.tcp_port,
                    args.poller_user,
                    args.poller_password,
                    seed,
                    args.timeout,
                    args.restart_cmd,
                    args.compose_dir,
                )
            )
    finally:
        _cleanup(args.host, args.tcp_port, args.poller_user, args.poller_password, args.timeout)

    if all(results):
        print("[SUMMARY] all checks passed")
        return 0
    print("[SUMMARY] one or more checks failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
