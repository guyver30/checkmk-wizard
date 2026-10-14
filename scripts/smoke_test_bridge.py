"""Two-broker Mosquitto bridge smoke test for the cloud MQTT contract.

This is the gate for the bridge behaviours the cloud feed relies on, proven on
two real `eclipse-mosquitto:2` brokers joined by an `mqttv50` bridge instead of
being assumed from reading the Mosquitto source:

- REMAP   a message published locally on `sites/s1/<suffix>` arrives on the cloud
          broker as `app/123/s1/<suffix>` (prefix remap by the bridge `topic` line)
- A1      the MQTT v5 user property `event_id` set by a paho v5 publisher arrives
          unchanged at a cloud-side v5 subscriber
- A2      a retained message keeps its retain flag across the bridge, and an empty
          retained payload (tombstone) clears the cloud broker's retained copy
- A3      informational: whether the bridge re-sends retained messages after a
          reconnect (recorded, never fails the run)
- A4      the bridge is loaded from `include_dir`; A4-EMPTY: an empty include
          directory is tolerated
- A6      QoS 1 messages published during a WAN outage are delivered after it
- A8      `pattern write app/%u/#` confines a SEN login to its own subtree
          (ACL-OWN / ACL-OTHER), and the bridge's read grant is confined to its
          own site (SCOPE)

TLS (`bridge_cafile`) is NOT exercised: both brokers sit on one throwaway
container network and speak plaintext. Everything binds to 127.0.0.1 on random
ports with random per-run passwords, and every container, the network and the
temp dir are removed afterwards unless `--keep` is given.

Run: `uv run scripts/smoke_test_bridge.py [--engine docker|podman] [--keep]`.
Exit 0 when every required check passed, 1 otherwise, 2 when no container
engine is available. Not collected by pytest (no `test_*` names).
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

IMAGE = "eclipse-mosquitto:2"
SEN = "123"
OTHER_SEN = "999"
SITE = "s1"
OTHER_SITE = "s2"

REQUIRED_CHECKS = (
    "REMAP",
    "A1",
    "A2",
    "A4",
    "A4-EMPTY",
    "A6",
    "ACL-OWN",
    "ACL-OTHER",
    "SCOPE",
)


# ---------------------------------------------------------------- pure builders


def cloud_conf() -> str:
    return (
        "listener 1883\n"
        "allow_anonymous false\n"
        "password_file /mosquitto/config/passwd\n"
        "acl_file /mosquitto/config/acl\n"
    )


def cloud_acl() -> str:
    return "user archiver\ntopic read app/#\n\npattern write app/%u/#\n"


def local_conf() -> str:
    # max_queued_messages is only here to prove the directive parses ahead of the
    # listener; production values are set where the bridge template is deployed.
    return (
        "max_queued_messages 1000\n"
        "listener 1883\n"
        "allow_anonymous false\n"
        "password_file /mosquitto/config/passwd\n"
        "acl_file /mosquitto/config/acl\n"
        "include_dir /mosquitto/config/conf.d\n"
    )


def local_acl(site: str) -> str:
    return (
        f"user poller\ntopic readwrite sites/{site}/#\n\n"
        f"user bridge\ntopic read sites/{site}/#\n\n"
        f"user other\ntopic readwrite sites/{OTHER_SITE}/#\n"
    )


def bridge_conf(
    sen: str,
    site: str,
    remote_host: str,
    remote_password: str,
    bridge_password: str,
) -> str:
    return (
        f"connection cloud-{sen}-{site}\n"
        f"address {remote_host}:1883\n"
        "bridge_protocol_version mqttv50\n"
        f"remote_clientid bridge-{sen}-{site}\n"
        f"remote_username {sen}\n"
        f"remote_password {remote_password}\n"
        "local_username bridge\n"
        f"local_password {bridge_password}\n"
        "cleansession false\n"
        "bridge_session_expiry_interval 86400\n"
        "keepalive_interval 60\n"
        "restart_timeout 2\n"
        "notifications false\n"
        f"topic # out 1 sites/{site}/ app/{sen}/{site}/\n"
    )


def required_checks_passed(results: dict[str, bool | None]) -> bool:
    """True only when every required check is True; A3 is informational."""
    return all(results.get(name) is True for name in REQUIRED_CHECKS)


# ------------------------------------------------------------------ mqtt helpers


class Collector:
    """A connected v5 subscriber that records every message it receives."""

    def __init__(self, port: int, user: str, password: str, topic: str):
        self.messages: list[tuple[float, mqtt.MQTTMessage]] = []
        self._lock = threading.Lock()
        self._subscribed = threading.Event()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"smoke-sub-{uuid.uuid4().hex[:8]}",
            protocol=mqtt.MQTTv5,
        )
        self.client.username_pw_set(user, password)
        self.client.on_connect = lambda c, u, f, rc, p=None: c.subscribe(topic, qos=1)
        self.client.on_subscribe = lambda *a, **k: self._subscribed.set()
        self.client.on_message = self._on_message
        self.client.connect("127.0.0.1", port)
        self.client.loop_start()
        if not self._subscribed.wait(10):
            raise RuntimeError(f"subscriber {user} on {topic} never confirmed")

    def _on_message(self, client, userdata, msg):
        with self._lock:
            self.messages.append((time.monotonic(), msg))

    def snapshot(self) -> list[mqtt.MQTTMessage]:
        with self._lock:
            return [m for _, m in self.messages]

    def wait_for(self, predicate, timeout: float) -> mqtt.MQTTMessage | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self.snapshot():
                if predicate(msg):
                    return msg
            time.sleep(0.1)
        return None

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def _event_ids(msg: mqtt.MQTTMessage) -> list[str]:
    props = getattr(msg, "properties", None)
    pairs = getattr(props, "UserProperty", []) if props is not None else []
    return [v for k, v in pairs if k == "event_id"]


def _publish(
    port: int,
    user: str,
    password: str,
    topic: str,
    payload: bytes | str,
    retain: bool = False,
    event_id: str | None = None,
) -> bool:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"smoke-pub-{uuid.uuid4().hex[:8]}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(user, password)
    props = None
    if event_id is not None:
        props = Properties(PacketTypes.PUBLISH)
        props.UserProperty = ("event_id", event_id)
    try:
        client.connect("127.0.0.1", port)
        client.loop_start()
        info = client.publish(topic, payload, qos=1, retain=retain, properties=props)
        info.wait_for_publish(timeout=10)
        return info.is_published()
    finally:
        client.loop_stop()
        client.disconnect()


# ------------------------------------------------------------------ engine helpers


class Engine:
    def __init__(self, name: str):
        self.name = name

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.name, *args], capture_output=True, text=True, check=False
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"{self.name} {' '.join(args)} failed: {proc.stderr.strip()}"
            )
        return proc

    def host_port(self, container: str) -> int:
        out = self.run("port", container, "1883/tcp").stdout.strip().splitlines()[0]
        return int(out.rsplit(":", 1)[1])


def _wait_tcp(port: int, timeout: float) -> bool:
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _report(results: dict, name: str, ok: bool | None, detail: str = "") -> None:
    results[name] = ok
    label = "INFO" if ok is None else ("PASS" if ok else "FAIL")
    print(f"[{label}] {name}" + (f": {detail}" if detail else ""))


# ----------------------------------------------------------------------- driver


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o644)


def _make_passwd(engine: Engine, directory: Path, users: dict[str, str]) -> None:
    cmds = []
    for i, (user, pw) in enumerate(users.items()):
        flag = "-c -b" if i == 0 else "-b"
        cmds.append(f"mosquitto_passwd {flag} /work/passwd {user} {pw}")
    cmds.append("chmod 0644 /work/passwd")
    engine.run(
        "run", "--rm", "-v", f"{directory}:/work{_vol_suffix(engine)}", IMAGE,
        "sh", "-c", " && ".join(cmds),
    )  # fmt: skip


def _vol_suffix(engine: Engine) -> str:
    return ":Z" if engine.name == "podman" else ""


def _start_broker(
    engine: Engine, name: str, net: str, alias: str, config_dir: Path, publish: bool
) -> None:
    args = ["run", "-d", "--name", name, "--network", net, "--network-alias", alias]
    if publish:
        args += ["-p", "127.0.0.1::1883"]
    args += ["-v", f"{config_dir}:/mosquitto/config{_vol_suffix(engine)}", IMAGE]
    engine.run(*args)


def run_checks(engine: Engine, root: Path, timeout: float, rand: str) -> dict:
    results: dict[str, bool | None] = {}
    cloud_pw = {
        "archiver": secrets.token_urlsafe(16),
        SEN: secrets.token_urlsafe(16),
        OTHER_SEN: secrets.token_urlsafe(16),
    }
    local_pw = {
        "poller": secrets.token_urlsafe(16),
        "bridge": secrets.token_urlsafe(16),
        "other": secrets.token_urlsafe(16),
    }
    cloud_dir, local_dir, empty_dir = root / "cloud", root / "local", root / "empty"
    for d in (cloud_dir, local_dir, empty_dir):
        d.mkdir()
        d.chmod(0o777)

    _write(cloud_dir / "mosquitto.conf", cloud_conf())
    _write(cloud_dir / "acl", cloud_acl())
    _write(local_dir / "mosquitto.conf", local_conf())
    _write(local_dir / "acl", local_acl(SITE))
    _write(
        local_dir / "conf.d" / "bridge.conf",
        bridge_conf(SEN, SITE, "cloud", cloud_pw[SEN], local_pw["bridge"]),
    )
    _make_passwd(engine, cloud_dir, cloud_pw)
    _make_passwd(engine, local_dir, local_pw)
    # Third broker: same config, EMPTY conf.d (A4-EMPTY).
    for name in ("mosquitto.conf", "acl", "passwd"):
        shutil.copy(local_dir / name, empty_dir / name)
        (empty_dir / name).chmod(0o644)
    (empty_dir / "conf.d").mkdir()
    (empty_dir / "conf.d").chmod(0o755)

    net = f"smoke17-{rand}"
    cloud, local, empty = (f"smoke17-{k}-{rand}" for k in ("cloud", "local", "empty"))
    engine.run("network", "create", net)
    _start_broker(engine, cloud, net, "cloud", cloud_dir, publish=True)
    _start_broker(engine, local, net, "local", local_dir, publish=True)
    cloud_port, local_port = engine.host_port(cloud), engine.host_port(local)
    for port in (cloud_port, local_port):
        if not _wait_tcp(port, timeout):
            raise RuntimeError(f"broker on port {port} did not accept connections")

    arch_pw, poller_pw = cloud_pw["archiver"], local_pw["poller"]
    sub = Collector(cloud_port, "archiver", arch_pw, "app/#")
    try:
        # Bridge readiness: probe until the cloud sees a remapped non-retained message.
        deadline = time.monotonic() + timeout
        ready = False
        while time.monotonic() < deadline and not ready:
            _publish(local_port, "poller", poller_pw, f"sites/{SITE}/lan/ready", "x")
            ready = (
                sub.wait_for(
                    lambda m: m.topic == f"app/{SEN}/{SITE}/lan/ready", 1.0
                )
                is not None
            )
        if not ready:
            raise RuntimeError("bridge never connected the two brokers")

        # REMAP + A1
        eid = "smoke-" + uuid.uuid4().hex
        suffix = "lan/events/recent"
        _publish(local_port, "poller", poller_pw, f"sites/{SITE}/{suffix}", "[]",
                 event_id=eid)  # fmt: skip
        got = sub.wait_for(lambda m: m.topic == f"app/{SEN}/{SITE}/{suffix}", timeout)
        _report(results, "REMAP", got is not None,
                f"cloud topic {got.topic if got else 'nothing received'}")  # fmt: skip
        ids = _event_ids(got) if got is not None else []
        _report(results, "A1", eid in ids, f"sent {eid}, received {ids}")

        # A2: retain flag carried, then tombstone clears the cloud copy.
        status_suffix = "lan/devices/h1/status"
        _publish(local_port, "poller", poller_pw, f"sites/{SITE}/{status_suffix}",
                 json.dumps({"state": "UP"}), retain=True)  # fmt: skip
        time.sleep(2)
        late = Collector(cloud_port, "archiver", arch_pw, f"app/{SEN}/{SITE}/{status_suffix}")
        first = late.wait_for(lambda m: True, 3)
        retain_ok = first is not None and bool(first.retain)
        late.close()
        _publish(local_port, "poller", poller_pw, f"sites/{SITE}/{status_suffix}",
                 b"", retain=True)  # fmt: skip
        time.sleep(2)
        late2 = Collector(cloud_port, "archiver", arch_pw, f"app/{SEN}/{SITE}/{status_suffix}")
        leftover = late2.wait_for(lambda m: len(m.payload) > 0, 3)
        late2.close()
        _report(results, "A2", retain_ok and leftover is None,
                f"retain flag carried={retain_ok}, retained copy after tombstone="
                f"{'present' if leftover else 'cleared'}"
                " (an empty-payload copy is not a retained value)")  # fmt: skip

        # A4: bridge came from conf.d
        _report(results, "A4", results["REMAP"] is True, "bridge loaded via include_dir")

        # A4-EMPTY: third broker with an empty conf.d
        _start_broker(engine, empty, net, "empty", empty_dir, publish=False)
        time.sleep(3)
        running = engine.run(
            "inspect", "-f", "{{.State.Running}}", empty, check=False
        ).stdout.strip()
        logs = engine.run("logs", empty, check=False)
        log_text = logs.stdout + logs.stderr
        _report(results, "A4-EMPTY", running == "true" and "Error" not in log_text,
                f"running={running}, 'Error' in logs={'Error' in log_text}")  # fmt: skip

        # ACL-OWN / ACL-OTHER (direct cloud logins)
        _publish(cloud_port, SEN, cloud_pw[SEN], f"app/{SEN}/{SITE}/acl-check", "own")
        own = sub.wait_for(lambda m: m.topic == f"app/{SEN}/{SITE}/acl-check", 5)
        _report(results, "ACL-OWN", own is not None, "own subtree write delivered")
        _publish(cloud_port, SEN, cloud_pw[SEN], f"app/{OTHER_SEN}/{SITE}/acl-check", "x")
        other = sub.wait_for(lambda m: m.topic == f"app/{OTHER_SEN}/{SITE}/acl-check", 3)
        _report(results, "ACL-OTHER", other is None,
                "write to another SEN subtree " + ("DELIVERED" if other else "dropped"))  # fmt: skip

        # SCOPE: other site's local traffic must not reach the cloud
        _publish(local_port, "other", local_pw["other"], f"sites/{OTHER_SITE}/lan/x", "x")
        leak = sub.wait_for(lambda m: m.topic.endswith(f"/{OTHER_SITE}/lan/x")
                            or f"/{OTHER_SITE}/" in m.topic, 3)  # fmt: skip
        _report(results, "SCOPE", leak is None,
                "other site traffic " + ("LEAKED" if leak else "stayed local"))  # fmt: skip

        # A3 (informational), then A6. Both disconnect the local container, so they
        # run last and use `exec` instead of the (then unreliable) published port.
        retained_topic = f"sites/{SITE}/lan/a3/probe"
        _publish(local_port, "poller", poller_pw, retained_topic, "a3", retain=True)
        sub.wait_for(lambda m: m.topic == f"app/{SEN}/{SITE}/lan/a3/probe", 5)
        engine.run("network", "disconnect", net, local)
        time.sleep(3)
        before = sum(1 for m in sub.snapshot() if m.topic.endswith("/lan/a3/probe"))
        engine.run("network", "connect", "--alias", "local", net, local)
        time.sleep(15)
        after = sum(1 for m in sub.snapshot() if m.topic.endswith("/lan/a3/probe"))
        resent = after - before
        results["A3"] = resent >= 1
        print(f"[INFO] A3: retained message re-sent {resent} time(s) after reconnect")

        ids = ["smoke-a6-" + uuid.uuid4().hex for _ in range(5)]
        engine.run("network", "disconnect", net, local)
        for event_id in ids:
            engine.run(
                "exec", local, "mosquitto_pub", "-V", "mqttv5", "-q", "1",
                "-u", "poller", "-P", poller_pw,
                "-t", f"sites/{SITE}/history/metrics",
                "-m", json.dumps({"event_id": event_id}),
                "-D", "publish", "user-property", "event_id", event_id,
            )  # fmt: skip
        time.sleep(2)
        engine.run("network", "connect", "--alias", "local", net, local)
        deadline = time.monotonic() + timeout
        seen: set[str] = set()
        while time.monotonic() < deadline and len(seen) < len(ids):
            for m in sub.snapshot():
                if m.topic == f"app/{SEN}/{SITE}/history/metrics":
                    seen.update(i for i in _event_ids(m) if i in ids)
            time.sleep(0.5)
        _report(results, "A6", len(seen) == len(ids),
                f"{len(seen)}/{len(ids)} queued messages delivered after outage")  # fmt: skip
    finally:
        sub.close()
    return results


def _cleanup(engine: Engine, rand: str, root: Path) -> None:
    for kind in ("cloud", "local", "empty"):
        engine.run("rm", "-f", f"smoke17-{kind}-{rand}", check=False)
    engine.run("network", "rm", f"smoke17-{rand}", check=False)
    shutil.rmtree(root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", choices=["docker", "podman"])
    parser.add_argument("--keep", action="store_true", help="skip cleanup")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    name = args.engine or next(
        (e for e in ("docker", "podman") if shutil.which(e)), None
    )
    if name is None or shutil.which(name) is None:
        print("No container engine (docker/podman) found", file=sys.stderr)
        return 2
    engine = Engine(name)
    rand = secrets.token_hex(3)
    root = Path(tempfile.mkdtemp(prefix="smoke17-"))
    results: dict[str, bool | None] = {}
    try:
        results = run_checks(engine, root, args.timeout, rand)
    except Exception as exc:  # noqa: BLE001 - report harness failure, then clean up
        print(f"[FAIL] harness: {exc}")
    finally:
        if not args.keep:
            _cleanup(engine, rand, root)

    print("\nVerdicts:")
    for key in (*REQUIRED_CHECKS, "A3"):
        value = results.get(key)
        if key == "A3":
            label = "re-sent" if value else "not re-sent"
        else:
            label = "n/a" if value is None else ("PASS" if value else "FAIL")
        suffix = " (informational)" if key == "A3" else ""
        print(f"  {key:10s} {label}{suffix}")
    print("TLS (bridge_cafile) not exercised: plaintext on a throwaway network.")
    ok = required_checks_passed(results)
    print("RESULT: " + ("all required checks passed" if ok else "required check(s) FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
