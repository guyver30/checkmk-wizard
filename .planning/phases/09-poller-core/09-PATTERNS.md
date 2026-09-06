# Phase 9: Poller Core - Pattern Map

**Mapped:** 2026-09-06
**Files analyzed:** 3 (1 new script, 1 modified config, 1 discretionary test file)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/mqtt_poller.py` | service (standalone daemon) | streaming / pub-sub / request-response | `scripts/smoke_test_broker.py` (MQTT idiom) + `src/checkmk_wizard/livestatus.py` (Livestatus query idiom) | exact (composite) |
| `deploy/compose.yaml` | config | request-response (service wiring) | same file's own `worker` service block (lines 63-89) | exact |
| `tests/test_mqtt_poller.py` (Claude's discretion — see Note below) | test | request-response (mocked socket) / transform (pure-function checks) | `tests/test_livestatus.py` | role-match |

**Note on the test file:** `scripts/smoke_test_broker.py` (the Phase 8 precedent for "standalone script under `scripts/`") has **zero** corresponding unit-test file in `tests/` — it validates itself only via live invocation against a real broker. `mqtt_poller.py` differs in that it contains substantial pure logic (worst-of status aggregation, bounded-list truncation, topology diffing, LQL query construction) that is cheap and valuable to unit-test with mocked `socket`/`paho.mqtt.client`, the same way `tests/test_livestatus.py` mocks `socket.create_connection` for `livestatus.py`. Recommend the planner add `tests/test_mqtt_poller.py` for the pure/mockable pieces, while leaving end-to-end broker/Livestatus behavior to a live smoke-test addition (mirroring `scripts/smoke_test_broker.py`), not full pytest coverage of the network loop itself.

## Pattern Assignments

### `scripts/mqtt_poller.py` (service, streaming/pub-sub/request-response)

**Analog 1 (MQTT client lifecycle, CLI shape, error handling):** `scripts/smoke_test_broker.py`
**Analog 2 (Livestatus query mechanics):** `src/checkmk_wizard/livestatus.py`
**Analog 3 (dataclass/enum conventions):** `src/checkmk_wizard/remote.py`

**Module header / imports pattern** (`scripts/smoke_test_broker.py` lines 1-42):
```python
"""Live-broker smoke test proving BRK-01, BRK-02 and BRK-03 against a running Mosquitto.
...
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
```
Apply the same shape to `mqtt_poller.py`: module docstring stating purpose + why it's standalone (cite D-01's portability reasoning), `from __future__ import annotations` first, stdlib imports before third-party `paho.mqtt.client`. Add `import json`, `import logging`, `import os`, `import socket`, `import time` as needed; do **not** import anything from `checkmk_wizard` (D-01).

**MQTT client setup — v2 callback API, LWT before connect, reconnect backoff** (`scripts/smoke_test_broker.py` lines 42-95, esp. 70-93):
```python
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(user, password)
client.on_connect = on_connect
try:
    client.connect(host, tcp_port)
    client.loop_start()
    if not connected.wait(timeout=timeout):
        print(f"[FAIL] poller_publish: no CONNACK within {timeout}s")
        return False
    ...
finally:
    client.loop_stop()
    client.disconnect()
```
Combine with `will_set()` (must precede `connect()`) and `reconnect_delay_set()` per RESEARCH.md's own worked example (Code Examples section) — that example is already written in this exact idiom, cite it directly as the template for `build_mqtt_client()`.

**Bounded wait for a retained message (startup reconciliation, PLR-02)** (`scripts/smoke_test_broker.py` lines 199-232, `_wait_for_retained_payload`):
```python
def _wait_for_retained_payload(host, port, user, password, topic, timeout) -> bytes | None:
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
```
Copy this near-verbatim for `reconcile_topology()` (RESEARCH.md Pattern 1 already adapts it), subscribing only to `lan/devices/topology` per the resolved reconciliation strategy — note the closure-in-loop avoidance rationale (ruff B023) called out in the analog's own comment (lines 209-212), relevant if the poller ever builds similar per-cycle closures.

**Tombstone publish (empty retained payload)** (`scripts/smoke_test_broker.py` lines 288-307, `_cleanup`):
```python
info = client.publish(topic, payload=None, retain=True)
info.wait_for_publish(timeout=timeout)
```
Apply directly for PLR-06 device removal — publish `payload=None, retain=True` (add `qos=1` per the resolved QoS table) to both `lan/devices/{id}/status` and `lan/devices/{id}/history`.

**CLI/config entry point pattern** (`scripts/smoke_test_broker.py` lines 310-330, `main()`):
```python
def main() -> int:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--tcp-port", type=int, default=1883)
    ...
    args = parser.parse_args()
    ...

if __name__ == "__main__":
    sys.exit(main())
```
D-04 requires env-var configuration (not CLI flags) for the poller's actual runtime — so the equivalent pattern here is `PollerConfig` populated from `os.environ.get(...)` with the same defaulting style already used in this repo (see Shared Patterns "Env-var configuration" below), rather than `argparse`. `argparse` in `smoke_test_broker.py` is for a manually-invoked live test, not the always-running poller; do not copy `argparse` itself, only the top-level `def main() -> int: ... ; sys.exit(main())` and `if __name__ == "__main__":` shape.

**Error handling pattern — narrow except, log-and-continue** (`scripts/smoke_test_broker.py` lines 87-89, 183-185, 273-275; matches `src/checkmk_wizard/scanner.py`/`remote.py` convention):
```python
except (TimeoutError, OSError) as exc:
    print(f"[FAIL] poller_publish: {exc}")
    return False
```
For the poller's per-cycle Livestatus query and JSON parse, use the same narrow-except philosophy: `except (TimeoutError, OSError)` for the socket call, `except (json.JSONDecodeError, ValueError)` for the parse (per RESEARCH.md Security Domain / STRIDE table), log and skip to next cycle — never a bare `except Exception`.

---

### Livestatus query (embedded in `scripts/mqtt_poller.py`)

**Analog:** `src/checkmk_wizard/livestatus.py` (full file, 56 lines)

**One-shot connect/send/read-until-EOF pattern** (lines 27-44):
```python
query = (
    "GET hosts\n"
    "Columns: name state\n"
    "OutputFormat: csv\n"
    "ColumnHeaders: off\n"
    "\n"
)
with socket.create_connection((host, port), timeout=10) as sock:
    sock.sendall(query.encode())
    sock.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)

text = b"".join(chunks).decode(errors="replace")
```
Extend, don't replace: same `socket.create_connection(..., timeout=...)` context-manager idiom, same `sendall` + `shutdown(SHUT_WR)` + `recv`-until-empty loop, same `decode(errors="replace")` — only the `Columns:`/`OutputFormat:` header values change (switch to `OutputFormat: json` per RESEARCH.md Pattern 2, richer column list). Keep `DEFAULT_PORT = 6557` as the same-named module constant if `mqtt_poller.py` needs its own default (it will diverge from `livestatus.py`'s module since this is a separate standalone script, but the constant name/value should match for consistency).

**Module docstring convention** (lines 1-9): cites why TCP not UNIX socket, cites which wizard function enables it. `mqtt_poller.py`'s docstring should follow the same "why this transport, why this shape" convention, and should explicitly contrast itself with `docs/src/mqtt_publisher_changes.py`'s deprecated UNIX-socket + v1-paho-mqtt-API approach (see Anti-Pattern note below).

---

### `deploy/compose.yaml` (config)

**Analog:** the file's own existing `worker` service block (lines 63-89)

**Env-var + restart-policy + network pattern to copy:**
```yaml
  worker:
    image: python:3.12-slim
    container_name: automation-worker
    restart: unless-stopped
    working_dir: /app
    volumes:
      - ./app:/app:z
    environment:
      - CMK_REST_API=http://checkmk:5000/dmc/check_mk/api/1.0
      - CMK_SITE=dmc
      - MQTT_HOST=mosquitto
      - MQTT_PORT=1883
      ...
    networks:
      - cmk_net
```
New `poller` service should copy: `restart: unless-stopped` (D-02), `networks: [cmk_net]`, the `MQTT_HOST=mosquitto` / `MQTT_PORT=1883` env-var names verbatim (D-04 says "same pattern as `worker`'s existing `MQTT_HOST`/`MQTT_PORT`"), plus new poller-specific vars (`MQTT_USERNAME`, `MQTT_PASSWORD`, `LIVESTATUS_HOST=checkmk`, `LIVESTATUS_PORT=6557`, `POLL_INTERVAL_SECONDS=60`, `HISTORY_MAX_ENTRIES=20`, `EVENTS_MAX_ENTRIES=50`, `RECONCILE_TIMEOUT_SECONDS=5`).

**Deviate from the `worker` analog on volumes** — do NOT copy `volumes: - ./app:/app:z`. Per RESEARCH.md Common Pitfalls (Pitfall A), `./app` is not committed to git and would leave the `poller` service with no script on a fresh checkout. Instead bind-mount the git-tracked `scripts/` directory read-only:
```yaml
    volumes:
      - ../scripts:/scripts:ro,z
```
and set `command`/`entrypoint` to run `uv run python /scripts/mqtt_poller.py` (or install `paho-mqtt` directly via `pip install paho-mqtt` in a minimal `python:3.12-slim` image, matching the `worker` service's own inline `pip install --no-cache-dir uv` pattern at line 86, since the poller doesn't need a full `uv`-managed project — it only needs stdlib + `paho-mqtt`).

**Mosquitto credentials this service must consume** (`deploy/mosquitto.acl` lines 9-10, already provisioned in Phase 8):
```
user poller
topic readwrite #
```
Confirms `MQTT_USERNAME=poller` (matching an existing `deploy/mosquitto.passwd` entry) is the correct credential to inject via env var — no new ACL/user work needed this phase.

---

### `tests/test_mqtt_poller.py` (discretionary — pure-function/mocked-socket coverage)

**Analog:** `tests/test_livestatus.py` (full file, 71 lines)

**Mocked-socket test pattern** (lines 1-27):
```python
import socket
from unittest.mock import MagicMock, patch

from checkmk_wizard import livestatus


def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    chunks = [response, b""]
    sock.recv.side_effect = chunks
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock


def test_query_host_states_connects_over_tcp_to_default_port():
    sock = _fake_connection(b"web1;0\n")
    with patch("socket.create_connection", return_value=sock) as mock_connect:
        livestatus.query_host_states("checkmk", ["web1"])
    mock_connect.assert_called_once_with(("checkmk", livestatus.DEFAULT_PORT), timeout=10)
```
Since `mqtt_poller.py` lives under `scripts/`, not `src/checkmk_wizard/`, the import will need `sys.path` manipulation or an `importlib`-based load (there is no existing precedent for importing a `scripts/*.py` module from `tests/` in this repo — `scripts/smoke_test_broker.py` has no test at all). Simplest approach consistent with the repo's low-ceremony test style: add `scripts` to `sys.path` at the top of the test module, or `spec_from_file_location`. Apply the same `patch("socket.create_connection", ...)` mocking style for the Livestatus query function, and `unittest.mock.patch`/`MagicMock` (not a mocking framework) for `paho.mqtt.client.Client` when testing the pure aggregation/diff/bounded-list functions in isolation (those functions themselves need no mocking at all — test them as plain unit functions, e.g. `compute_overall_state(0, 2) == "CRIT"`, `append_bounded([...], entry, 2)`).

## Shared Patterns

### MQTT v2 callback API + LWT + reconnect backoff
**Source:** `scripts/smoke_test_broker.py` (whole-file idiom, esp. lines 66-93, 396-423 of RESEARCH.md's own worked `build_mqtt_client()` example)
**Apply to:** `scripts/mqtt_poller.py` — every MQTT client instantiation (main publisher client, and any short-lived reconciliation client) must use `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)`, `will_set()` before `connect()`, `reconnect_delay_set(min_delay=1, max_delay=120)`, `loop_start()`/`loop_stop()` bracketing.

### Env-var configuration (no config files)
**Source:** `deploy/compose.yaml` `worker` service environment block (lines 72-84) + `src/checkmk_wizard/wizard.py:290` (`os.environ.get("CMK_SITE_ID", "")`)
**Apply to:** `scripts/mqtt_poller.py`'s `PollerConfig` construction — read every setting via `os.environ.get("VAR_NAME", "<default>")`, matching D-04's "same pattern as worker's existing MQTT_HOST/MQTT_PORT" instruction. Never read a config file.

### Narrow exception handling, log-and-continue per cycle
**Source:** `scripts/smoke_test_broker.py` lines 87-89 / 183-185 / 273-275; `src/checkmk_wizard/scanner.py:38`; `src/checkmk_wizard/remote.py:168`
**Apply to:** the Livestatus query call site (`except (TimeoutError, OSError)`) and the JSON-parse call site (`except (json.JSONDecodeError, ValueError)`) inside the per-cycle poll loop — log and `continue`/skip to next sleep, never let one bad cycle kill the daemon (matches RESEARCH.md's own "Don't Hand-Roll" guidance: the poll interval is itself the retry backoff).

### Dataclasses for structured records
**Source:** `src/checkmk_wizard/remote.py` lines 40-70 (`SSHCredentials`, `PortProbeResult`, `ActionResult`); `src/checkmk_wizard/api.py` lines 30-34 (`CheckmkConnection`)
**Apply to:** `PollerConfig`, per-device status record, topology node record — plain `@dataclass`, no Pydantic, mutable-default fields via `field(default_factory=list)` if any list/dict fields are needed (matches `src/checkmk_wizard/scanner.py:25`'s `HostScanResult.open_ports`).

### Tri-state / enum values as `str, Enum`
**Source:** `src/checkmk_wizard/remote.py` lines 34-37 (`class Outcome(str, Enum)`)
**Apply to:** if the poller models overall device status as an enum rather than a bare string (optional — PLR-03's five literal values `OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN` could be a plain `str` return per RESEARCH.md Pattern 3's `compute_overall_state()`, which already returns a bare `str`) — either is acceptable; if an enum is chosen for type-safety, follow this `str, Enum` subclassing convention so it still serializes as a plain string into the JSON payload.

## No Analog Found

None — every file in scope has at least a role-match or better. The one **anti-pattern** worth flagging explicitly (not a missing analog, but a "don't copy this" note):

| File | Reason |
|------|--------|
| `docs/src/mqtt_publisher_changes.py` | Superficially the closest same-domain file (Livestatus → MQTT publisher) but is explicitly deprecated per this repo's own CLAUDE.md and RESEARCH.md's "State of the Art" table: v1 paho-mqtt callback API (no `CallbackAPIVersion.VERSION2`), UNIX-socket Livestatus access (`/omd/sites/monitoring/tmp/run/live`, incompatible with this project's container-boundary constraint), full-blob retained topic instead of per-entity topics, and file-based state (`STATE_FILE`/`HISTORY_FILE`) instead of the resolved broker-reconciliation strategy. Reference only — do not copy any code from it. |

## Conventions

Convention derivation was attempted via the shared deterministic module (`node bin/gsd-tools.cjs verify conventions --derive`, both repo-wide and scoped to `scripts/` and `src/`) and returned `{"skipped": true, "reason": "no-readable-files"}` in every invocation — this tool's file-extension detection appears scoped to JS/TS-style projects and does not recognize this repo's all-Python (`.py`) source tree. No `## Conventions` axis table can be derived mechanically for this phase; the manually-observed conventions already documented throughout this repo's `CLAUDE.md` (snake_case, `@dataclass`, `from __future__ import annotations`, module-specific `*Error` exceptions) remain authoritative and are reflected in the Pattern Assignments and Shared Patterns sections above.

## Metadata

**Analog search scope:** `scripts/`, `src/checkmk_wizard/`, `tests/`, `deploy/`, `docs/src/`
**Files scanned:** `scripts/smoke_test_broker.py`, `src/checkmk_wizard/livestatus.py`, `src/checkmk_wizard/api.py`, `src/checkmk_wizard/remote.py`, `tests/test_livestatus.py`, `deploy/compose.yaml`, `deploy/mosquitto.acl`, `docs/src/mqtt_publisher_changes.py`, `pyproject.toml`
**Pattern extraction date:** 2026-09-06
