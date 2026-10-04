"""Live-broker smoke test proving BRK-01, BRK-02 and BRK-03 against a running Mosquitto.

This project's `tests/` suite is 100% mocked and never touches live
infrastructure (see `tests/test_*.py`), so it cannot prove any of the three
broker-hardening requirements this phase delivers. This script is
deliberately standalone, run via `uv run python scripts/smoke_test_broker.py`
against a real deployment host — not collected by pytest (no `test_*`
function names, not under `tests/`).

`--poller-password`/`--ws-password` default from the MQTT_POLLER_PASSWORD/WS_PASSWORD
environment variables (falling back to the disposable `poller`/`wsreader` dev values if
unset), so the usual invocation sources deploy/.env first:
`set -a; . deploy/.env; set +a; uv run python scripts/smoke_test_broker.py`.

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
- `check_wsadmin_publish_admin_cmd`, `check_wsadmin_publish_lan_denied`,
  `check_wsadmin_reads_lan`, `check_wsreader_cannot_read_admin` — the admin
  broker user's grants: wsadmin may publish `sites/<id>/admin/cmd` only, may
  read `sites/<id>/lan/#`, and wsreader cannot see admin topics. They use the
  same independent-subscriber design as `check_ws_publish_denied`, and are
  skipped (not failed) when ADMIN_WS_PASSWORD is unset. The usual invocation
  is `set -a; . deploy/.env; set +a; uv run python scripts/smoke_test_broker.py`.
- `check_analytics_writes_allowed`, `check_analytics_incident_status_denied`,
  `check_wstriage_publish_cmd`, `check_wstriage_publish_lan_denied` — the
  analytics and triage logins' grants: analytics may write
  `lan/needs/...` and `lan/incidents/<id>/narration` (the latter proves a `+`
  in an ACL write line works) but not `lan/incidents/<id>/status`, which is the
  poller's; wstriage may publish only `sites/<id>/needs/triage/cmd`. Each is
  skipped when its password (MQTT_ANALYTICS_PASSWORD / TRIAGE_WS_PASSWORD) is
  unset. Probes are non-retained so nothing is left on the broker.
- `check_persistence_across_restart` — a retained message survives a
  broker restart (BRK-02), skipped via `--skip-restart` for callers (e.g.
  the worker container) that must not restart a sibling service.

Topics live under `sites/<site-id>/...`; `--site-id` (default $CMK_SITE_ID,
else `dmc`) must equal the deployment's CMK_SITE_ID, because the broker ACL is
rendered from it at container start.

On dmc-server pass `--skip-restart`: restarting a single container breaks
Checkmk egress there. The full-stack procedure is
`podman compose down && podman compose up -d`.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

SMOKETEST_SEED_SUFFIX = "lan/smoketest/seed"
SMOKETEST_DENY_SUFFIX = "lan/smoketest/deny-check"
_SITE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")


def _site_topic(site_id: str, suffix: str) -> str:
    """The single place the per-site topic prefix is formatted."""
    return f"sites/{site_id}/{suffix}"


def check_poller_publish(
    host: str,
    site_id: str,
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
        info = client.publish(_site_topic(site_id, SMOKETEST_SEED_SUFFIX), seed, qos=1, retain=True)
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
    site_id: str,
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
        client.subscribe(_site_topic(site_id, f"{SMOKETEST_SEED_SUFFIX.rsplit('/', 1)[0]}/#"))
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
    site_id: str,
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
    deny_topic = _site_topic(site_id, SMOKETEST_DENY_SUFFIX)
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
        privileged.subscribe(deny_topic)
        privileged.loop_start()

        publisher.connect(host, ws_port)
        publisher.loop_start()
        # Return code/PUBACK from this publish is intentionally never
        # checked — MQTT 3.1.1 acknowledges it regardless of ACL outcome.
        publisher.publish(deny_topic, "should-never-arrive", qos=1, retain=True)
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


def _delivered(
    host: str,
    sub_port: int,
    sub_transport: str,
    sub_auth: tuple[str, str],
    pub_port: int,
    pub_transport: str,
    pub_auth: tuple[str, str],
    sub_topic: str,
    pub_topic: str,
    payload: str,
    timeout: float,
) -> bool | None:
    """Publish once (non-retained) and report whether the subscriber received it.

    Returns None on a connection error. The subscriber is confirmed subscribed
    (SUBACK) before publishing, and the publisher's own PUBACK is never
    trusted (see the module docstring): delivery is judged only from the
    independent subscriber within a bounded wait.
    """
    received = threading.Event()
    subscribed = threading.Event()

    def on_message(client, userdata, msg):
        received.set()

    def on_subscribe(client, userdata, mid, reason_codes, properties=None):
        subscribed.set()

    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=sub_transport)
    subscriber.username_pw_set(*sub_auth)
    subscriber.on_message = on_message
    subscriber.on_subscribe = on_subscribe
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=pub_transport)
    publisher.username_pw_set(*pub_auth)
    try:
        subscriber.connect(host, sub_port)
        subscriber.subscribe(sub_topic)
        subscriber.loop_start()
        subscribed.wait(timeout=timeout)
        publisher.connect(host, pub_port)
        publisher.loop_start()
        publisher.publish(pub_topic, payload, qos=1, retain=False)
        return received.wait(timeout=timeout)
    except (TimeoutError, OSError):
        return None
    finally:
        publisher.loop_stop()
        publisher.disconnect()
        subscriber.loop_stop()
        subscriber.disconnect()


def _report(name: str, ok: bool | None, fail_detail: str) -> bool:
    if ok:
        print(f"[PASS] {name}")
        return True
    print(f"[FAIL] {name}: {fail_detail}")
    return False


def check_wsadmin_publish_admin_cmd(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    admin_user: str,
    admin_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """wsadmin can publish on sites/<id>/admin/cmd; the poller-side subscriber receives it.

    A running poller will log and ack "unknown action" for this probe, which
    is harmless.
    """
    probe = f'{{"id": "smoke-{seed}", "action": "smoke", "hosts": []}}'
    ok = _delivered(
        host, tcp_port, "tcp", (poller_user, poller_password),
        ws_port, "websockets", (admin_user, admin_password),
        _site_topic(site_id, "admin/cmd"), _site_topic(site_id, "admin/cmd"), probe, timeout,
    )
    return _report("wsadmin_publish_admin_cmd", ok, "sites/<id>/admin/cmd publish did not arrive (or connection failed)")


def check_wsadmin_publish_lan_denied(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    admin_user: str,
    admin_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """A wsadmin publish under sites/<id>/lan/ must never reach the privileged subscriber."""
    topic = _site_topic(site_id, f"lan/smoke/{seed}")
    ok = _delivered(
        host, tcp_port, "tcp", (poller_user, poller_password),
        ws_port, "websockets", (admin_user, admin_password),
        topic, topic, "should-never-arrive", timeout,
    )
    if ok is None:
        return _report("wsadmin_publish_lan_denied", False, "connection failed")
    return _report("wsadmin_publish_lan_denied", not ok, "wsadmin publish under sites/<id>/lan/ was delivered (ACL not enforced)")


def check_wsadmin_reads_lan(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    admin_user: str,
    admin_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """A wsadmin WebSocket subscriber receives what the poller publishes under sites/<id>/lan/."""
    topic = _site_topic(site_id, f"lan/smoke/{seed}/admin-read")
    ok = _delivered(
        host, ws_port, "websockets", (admin_user, admin_password),
        tcp_port, "tcp", (poller_user, poller_password),
        _site_topic(site_id, "lan/smoke/#"), topic, "hello", timeout,
    )
    return _report("wsadmin_reads_lan", ok, "wsadmin did not receive a sites/<id>/lan/ message")


def check_analytics_writes_allowed(
    host: str,
    site_id: str,
    tcp_port: int,
    poller_user: str,
    poller_password: str,
    analytics_user: str,
    analytics_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """analytics can publish under lan/needs/ and lan/incidents/<id>/narration.

    Both probes must reach the poller-side subscriber; the narration one proves
    `+` in an ACL write line works on the broker.
    """
    ok = True
    for suffix in ("lan/needs/smoketest/status", "lan/incidents/smoketest/narration"):
        topic = _site_topic(site_id, suffix)
        delivered = _delivered(
            host, tcp_port, "tcp", (poller_user, poller_password),
            tcp_port, "tcp", (analytics_user, analytics_password),
            topic, topic, f"smoke-{seed}", timeout,
        )
        ok = bool(delivered) and ok
    return _report("analytics_writes_allowed", ok, "an allowed analytics publish did not arrive (or connection failed)")


def check_analytics_incident_status_denied(
    host: str,
    site_id: str,
    tcp_port: int,
    poller_user: str,
    poller_password: str,
    analytics_user: str,
    analytics_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """An analytics publish on lan/incidents/<id>/status must not be delivered (D-29)."""
    topic = _site_topic(site_id, "lan/incidents/smoketest/status")
    delivered = _delivered(
        host, tcp_port, "tcp", (poller_user, poller_password),
        tcp_port, "tcp", (analytics_user, analytics_password),
        topic, topic, f"smoke-{seed}", timeout,
    )
    if delivered is None:
        return _report("analytics_incident_status_denied", False, "connection failed")
    return _report("analytics_incident_status_denied", not delivered, "analytics publish on incidents/<id>/status was delivered (ACL not enforced)")


def check_wstriage_publish_cmd(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    analytics_user: str,
    analytics_password: str,
    triage_user: str,
    triage_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """wstriage can publish sites/<id>/needs/triage/cmd; the analytics login receives it."""
    topic = _site_topic(site_id, "needs/triage/cmd")
    ok = _delivered(
        host, tcp_port, "tcp", (analytics_user, analytics_password),
        ws_port, "websockets", (triage_user, triage_password),
        topic, topic, f'{{"id": "smoke-{seed}", "action": "smoke"}}', timeout,
    )
    return _report("wstriage_publish_cmd", ok, "sites/<id>/needs/triage/cmd publish did not arrive (or connection failed)")


def check_wstriage_publish_lan_denied(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    triage_user: str,
    triage_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """A wstriage publish under sites/<id>/lan/ must never reach the privileged subscriber."""
    topic = _site_topic(site_id, f"lan/smoke/{seed}/triage")
    delivered = _delivered(
        host, tcp_port, "tcp", (poller_user, poller_password),
        ws_port, "websockets", (triage_user, triage_password),
        topic, topic, "should-never-arrive", timeout,
    )
    if delivered is None:
        return _report("wstriage_publish_lan_denied", False, "connection failed")
    return _report("wstriage_publish_lan_denied", not delivered, "wstriage publish under sites/<id>/lan/ was delivered (ACL not enforced)")


def check_wsreader_cannot_read_admin(
    host: str,
    site_id: str,
    tcp_port: int,
    ws_port: int,
    poller_user: str,
    poller_password: str,
    ws_user: str,
    ws_password: str,
    seed: str,
    timeout: float,
) -> bool:
    """wsreader subscribed to sites/<id>/admin/# must receive nothing the poller publishes there."""
    ok = _delivered(
        host, ws_port, "websockets", (ws_user, ws_password),
        tcp_port, "tcp", (poller_user, poller_password),
        _site_topic(site_id, "admin/#"), _site_topic(site_id, "admin/ack"), f'{{"id": "smoke-{seed}"}}', timeout,
    )
    if ok is None:
        return _report("wsreader_cannot_read_admin", False, "connection failed")
    return _report("wsreader_cannot_read_admin", not ok, "wsreader received a sites/<id>/admin/ message (ACL not enforced)")


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
    site_id: str,
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
            payload = _wait_for_retained_payload(
                host, tcp_port, user, password, _site_topic(site_id, SMOKETEST_SEED_SUFFIX), timeout
            )
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


def _cleanup(host: str, site_id: str, tcp_port: int, user: str, password: str, timeout: float) -> None:
    """Clear the retained smoke-test topics so no ghosts leak into sites/<id>/lan/#.

    Run from a `finally` block regardless of check outcome. A cleanup
    failure is reported as a warning only — it never flips the overall
    pass/fail result.
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    try:
        client.connect(host, tcp_port)
        client.loop_start()
        for topic in (
            _site_topic(site_id, SMOKETEST_SEED_SUFFIX),
            _site_topic(site_id, SMOKETEST_DENY_SUFFIX),
        ):
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
    parser.add_argument(
        "--site-id",
        default=os.environ.get("CMK_SITE_ID", "dmc"),
        help="must equal the deployment's CMK_SITE_ID (source deploy/.env first)",
    )
    parser.add_argument("--tcp-port", type=int, default=1883)
    parser.add_argument("--ws-port", type=int, default=9002)
    parser.add_argument("--poller-user", default="poller")
    parser.add_argument("--poller-password", default=os.environ.get("MQTT_POLLER_PASSWORD", "poller"))
    parser.add_argument("--ws-user", default="wsreader")
    parser.add_argument("--ws-password", default=os.environ.get("WS_PASSWORD", "wsreader"))
    parser.add_argument("--admin-ws-user", default="wsadmin")
    parser.add_argument("--admin-ws-password", default=os.environ.get("ADMIN_WS_PASSWORD", ""))
    parser.add_argument("--analytics-user", default="analytics")
    parser.add_argument("--analytics-password", default=os.environ.get("MQTT_ANALYTICS_PASSWORD", ""))
    parser.add_argument("--triage-ws-user", default="wstriage")
    parser.add_argument("--triage-ws-password", default=os.environ.get("TRIAGE_WS_PASSWORD", ""))
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--restart-cmd", default="podman compose restart mosquitto")
    parser.add_argument("--compose-dir", default="deploy")
    args = parser.parse_args()
    if not _SITE_ID_RE.fullmatch(args.site_id):
        print(f"[ERROR] invalid --site-id {args.site_id!r}: must match [A-Za-z][A-Za-z0-9_]{{0,15}}")
        return 2

    seed = uuid.uuid4().hex
    results: list[bool] = []
    try:
        results.append(
            check_poller_publish(args.host, args.site_id, args.tcp_port, args.poller_user, args.poller_password, seed, args.timeout)
        )
        results.append(
            check_ws_subscribe(args.host, args.site_id, args.ws_port, args.ws_user, args.ws_password, seed, args.timeout)
        )
        results.append(
            check_ws_publish_denied(
                args.host,
                args.site_id,
                args.tcp_port,
                args.ws_port,
                args.poller_user,
                args.poller_password,
                args.ws_user,
                args.ws_password,
                args.timeout,
            )
        )
        if args.admin_ws_password:
            admin_args = (
                args.host,
                args.site_id,
                args.tcp_port,
                args.ws_port,
                args.poller_user,
                args.poller_password,
                args.admin_ws_user,
                args.admin_ws_password,
                seed,
                args.timeout,
            )
            results.append(check_wsadmin_publish_admin_cmd(*admin_args))
            results.append(check_wsadmin_publish_lan_denied(*admin_args))
            results.append(check_wsadmin_reads_lan(*admin_args))
            results.append(
                check_wsreader_cannot_read_admin(
                    args.host,
                    args.site_id,
                    args.tcp_port,
                    args.ws_port,
                    args.poller_user,
                    args.poller_password,
                    args.ws_user,
                    args.ws_password,
                    seed,
                    args.timeout,
                )
            )
        else:
            print("[SKIP] wsadmin checks: ADMIN_WS_PASSWORD not set")
        if args.analytics_password:
            analytics_args = (
                args.host,
                args.site_id,
                args.tcp_port,
                args.poller_user,
                args.poller_password,
                args.analytics_user,
                args.analytics_password,
                seed,
                args.timeout,
            )
            results.append(check_analytics_writes_allowed(*analytics_args))
            results.append(check_analytics_incident_status_denied(*analytics_args))
        else:
            print("[SKIP] analytics checks: MQTT_ANALYTICS_PASSWORD not set")
        if args.triage_ws_password and args.analytics_password:
            results.append(
                check_wstriage_publish_cmd(
                    args.host, args.site_id, args.tcp_port, args.ws_port,
                    args.analytics_user, args.analytics_password,
                    args.triage_ws_user, args.triage_ws_password,
                    seed, args.timeout,
                )
            )
            results.append(
                check_wstriage_publish_lan_denied(
                    args.host, args.site_id, args.tcp_port, args.ws_port,
                    args.poller_user, args.poller_password,
                    args.triage_ws_user, args.triage_ws_password,
                    seed, args.timeout,
                )
            )
        else:
            print("[SKIP] wstriage checks: TRIAGE_WS_PASSWORD or MQTT_ANALYTICS_PASSWORD not set")
        if args.skip_restart:
            print("[SKIP] persistence_across_restart (--skip-restart)")
        else:
            results.append(
                check_persistence_across_restart(
                    args.host,
                    args.site_id,
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
        _cleanup(args.host, args.site_id, args.tcp_port, args.poller_user, args.poller_password, args.timeout)

    if all(results):
        print("[SUMMARY] all checks passed")
        return 0
    print("[SUMMARY] one or more checks failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
