---
phase: 09-poller-core
reviewed: 2026-09-09T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - deploy/compose.yaml
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - scripts/mqtt_poller.py
  - scripts/smoke_test_poller.py
  - tests/test_mqtt_poller.py
findings:
  critical: 2
  warning: 7
  info: 2
  total: 11
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-09-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

The poller core (`scripts/mqtt_poller.py`) is well-documented and its stated design goals (per-row defensive parsing, resilient publish helpers, self-healing reconciliation from retained MQTT state) are largely implemented correctly and are backed by a genuinely thorough unit test suite. However, two of those stated guarantees are not actually met by the code:

1. `query_devices()` claims to defensively skip a malformed row rather than crash the poll loop (T-09-03), but several optional-column extractions either have no exception handling at all or an `except` clause that omits `IndexError`, so a short/malformed Livestatus row raises an uncaught exception that propagates out of the poll loop and kills the `restart: unless-stopped` container.
2. The poller's liveness contract (PLR-07: retained `lan/poller/status` should reliably reflect online/offline) is broken on the fatal-startup error path: the process publishes an "online" birth message, then exits after a graceful `client.disconnect()` without ever publishing `{"status": "offline"}` — and a graceful MQTT DISCONNECT suppresses the LWT, so the dashboard is left believing the poller is alive indefinitely.

Both are concretely reachable in ordinary operation (a truncated/odd Livestatus response; Livestatus TCP not yet enabled at first boot, which the project's own deployment doc documents as a manual one-time step) and neither is covered by the existing test suite. Several lower-severity robustness/packaging issues are also noted below.

## Critical Issues

### CR-01: Uncaught `IndexError` in `query_devices()` can crash the poll loop on a malformed row

**File:** `scripts/mqtt_poller.py:420-443`
**Issue:** `query_devices()`'s own docstring states: "a malformed response, a topic-unsafe host name, or a non-numeric state field skips that one row ... rather than crashing the poll loop" (T-09-03). The `name`/`state` extraction correctly guards against `IndexError`/`TypeError`, but several of the optional-column extractions do not:

```python
worst_service_state = 0
if "worst_service_state" in index:
    try:
        worst_service_state = int(row[index["worst_service_state"]])
    except (TypeError, ValueError):        # <-- IndexError not caught
        ...
        continue

downtime_depth = 0
if "scheduled_downtime_depth" in index:
    try:
        downtime_depth = int(row[index["scheduled_downtime_depth"]])
    except (TypeError, ValueError):        # <-- IndexError not caught
        downtime_depth = 0

acknowledged = bool(row[index["acknowledged"]]) if "acknowledged" in index else False   # unguarded
raw_parents = row[index["parents"]] if "parents" in index else None                     # unguarded
raw_tags = row[index["tags"]] if "tags" in index else None                              # unguarded
folder = derive_folder(row[index["filename"]]) if "filename" in index else ""           # unguarded
```

If a row returned by Livestatus is shorter than the requested column list (fewer elements than `len(columns)`), any of these `row[index[...]]` accesses raises `IndexError`. That exception is **not** a `LivestatusError`, so it is not caught by `run_forever()`'s per-cycle `except LivestatusError` handler (`scripts/mqtt_poller.py:826-836`) — it propagates all the way out of the `while` loop and terminates the process. `restart: unless-stopped` will just restart the container into the same crash on the next malformed row, i.e. a genuine crash-loop, contradicting the module's own stated resilience contract. No test in `tests/test_mqtt_poller.py` exercises a short/truncated row to catch this regression.

**Fix:** Add `IndexError` to the two existing `except` tuples, and wrap the currently-unguarded accesses the same way, e.g.:

```python
try:
    acknowledged = bool(row[index["acknowledged"]]) if "acknowledged" in index else False
except (IndexError, TypeError):
    acknowledged = False

try:
    raw_parents = row[index["parents"]] if "parents" in index else None
except (IndexError, TypeError):
    raw_parents = None
parents = list(raw_parents) if isinstance(raw_parents, list) else []

try:
    raw_tags = row[index["tags"]] if "tags" in index else None
except (IndexError, TypeError):
    raw_tags = None
tags = raw_tags if isinstance(raw_tags, dict) else {}

try:
    folder = derive_folder(row[index["filename"]]) if "filename" in index else ""
except (IndexError, TypeError):
    folder = ""
```
and change `except (TypeError, ValueError):` to `except (IndexError, TypeError, ValueError):` at lines 424 and 432. Add a regression test with a row shorter than `columns` to lock this in.

### CR-02: Retained `lan/poller/status` stays "online" forever after a fatal startup failure (LWT never fires on a graceful disconnect)

**File:** `scripts/mqtt_poller.py:790-815`, `scripts/mqtt_poller.py:887-910`
**Issue:** `build_mqtt_client()` publishes an "online" birth message from its `on_connect` callback as soon as the MQTT connection is established (`scripts/mqtt_poller.py:484-488`). In `run_forever()`, if the one-time Livestatus column probe fails (e.g. Livestatus-over-TCP not yet enabled — which the project's own deployment doc, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §5, documents as a manual one-time step performed *after* first bringup), the function logs the error and exits:

```python
except LivestatusError as exc:
    _logger.error("Cannot start: %s", exc)
    client.loop_stop()
    client.disconnect()
    return 1
```

`client.disconnect()` is a **graceful** MQTT disconnect (sends a DISCONNECT packet), which per the MQTT spec causes the broker to discard the client's Will Message — the LWT (`{"status": "offline"}`) is only delivered on an *ungraceful* disconnect. So on this path the broker's retained `lan/poller/status` is left at the birth-message value `{"status": "online", "last_poll": None, ...}` permanently, even though the poller process has exited with a non-zero code and is not running. Any dashboard staleness check based on `now - last_poll` (the mechanism this module's own comments cite for catching a stalled poller, `scripts/mqtt_poller.py:566-572`) cannot even compute an age here since `last_poll` is `None`. Contrast with the deliberate, correct graceful-shutdown handling at the *bottom* of `run_forever()` (`scripts/mqtt_poller.py:839-844`), which does explicitly republish `{"status": "offline"}` before disconnecting.

The same gap exists in `main()`'s `--once` mode: both its `LivestatusError` branch (`scripts/mqtt_poller.py:902-906`) and its normal-completion branch (`scripts/mqtt_poller.py:907-910`) call `client.loop_stop(); client.disconnect()` without ever publishing an offline status.

No test in `tests/test_mqtt_poller.py` exercises `run_forever()`'s startup-failure branch (the only `run_forever` test, `test_run_forever_survives_livestatus_error_and_does_not_raise`, targets the per-cycle `query_devices` failure, not `available_host_columns`), so this regression is not caught.

**Fix:** Publish the offline status before disconnecting on every early-exit path, e.g. factor out a helper and use it everywhere:

```python
def _shutdown(client: mqtt.Client) -> None:
    _publish_json(client, TOPIC_POLLER_STATUS, {"status": "offline"}, qos=1, retain=True)
    client.loop_stop()
    client.disconnect()
```
and call `_shutdown(client)` in place of the bare `client.loop_stop(); client.disconnect()` pairs at the `run_forever()` fatal-startup path and both `--once` exit paths.

## Warnings

### WR-01: `append_bounded()` / events truncation silently stop bounding when `max_entries` is `0`

**File:** `scripts/mqtt_poller.py:255-257`, `scripts/mqtt_poller.py:781`
**Issue:** `append_bounded()` truncates with `(entries + [entry])[-max_entries:]`, and `run_cycle()` truncates `state.events` the same way (`(state.events + events_this_cycle)[-config.events_max_entries:]`). In Python, `list[-0:]` is equivalent to `list[0:]` (since `-0 == 0`), which returns the **entire** list rather than an empty one. If an operator sets `HISTORY_MAX_ENTRIES=0` or `EVENTS_MAX_ENTRIES=0` (there is no validation preventing this — `_env_int` accepts any parseable integer), the intended "keep no history" configuration instead silently disables truncation entirely, growing the in-memory/retained payload without bound.
**Fix:** Guard the zero case explicitly, e.g.:
```python
def append_bounded(entries: list[dict], entry: dict, max_entries: int) -> list[dict]:
    if max_entries <= 0:
        return []
    return (entries + [entry])[-max_entries:]
```
and apply the same guard to the `state.events` truncation in `run_cycle()`.

### WR-02: No validation on numeric env vars — a zero/negative poll interval produces a tight busy-loop

**File:** `scripts/mqtt_poller.py:116-141`, `scripts/mqtt_poller.py:825-837`
**Issue:** `_env_int`/`_env_float` accept any parseable integer/float, including zero or negative values, for `POLL_INTERVAL_SECONDS`, `RECONCILE_TIMEOUT_SECONDS`, `HISTORY_MAX_ENTRIES`, and `EVENTS_MAX_ENTRIES`. `stop_event.wait(timeout=config.poll_interval_seconds)` with a zero/negative timeout returns immediately, turning the poll loop into a tight spin that hammers Livestatus and the MQTT broker as fast as the process can run, rather than failing fast with a clear error.
**Fix:** Clamp or reject non-positive values in `PollerConfig.from_env()`, e.g. `max(1, _env_int(...))` for `poll_interval_seconds`, or log an error and fall back to the documented default.

### WR-03: `reconcile_state()`'s wait on `topology_received` does not guarantee the events payload has arrived

**File:** `scripts/mqtt_poller.py:631-698`
**Issue:** The docstring explicitly documents that the wildcard per-device `history` subscription is "best-effort cosmetic restoration only" because a late-arriving retained message just gets rebuilt on the next transition — but the same race applies to `lan/events/recent`, which is *not* called out as best-effort. `reconcile_state()` proceeds as soon as the single `TOPIC_TOPOLOGY` retained message arrives (`topology_received.wait(...)`), with no guarantee that the separately-published `lan/events/recent` retained message has been delivered yet on the same subscribe batch. On a restart, this can silently reset `state.events` to `[]` even though the broker actually holds a non-empty retained events feed, discarding recent history from the dashboard's global events list.
**Fix:** Either wait on a second `events_received` `threading.Event` set from `on_message` for `TOPIC_EVENTS` (mirroring the topology wait, bounded by the same `reconcile_timeout_seconds`), or explicitly document/accept this as a second best-effort carve-out alongside history in the docstring.

### WR-04: `paho-mqtt` is a main dependency of the installable `checkmk-wizard` package despite `src/` never using it

**File:** `pyproject.toml:13`
**Issue:** `scripts/mqtt_poller.py`'s own module docstring (D-01) is explicit that it "must run independently of the wizard" and is deliberately kept out of `[project.scripts]` so it can be deployed without the wizard package. Yet `paho-mqtt>=2.1.0` is listed under `[project.dependencies]` (not `[dependency-groups] dev`), even though a repo-wide search confirms `src/checkmk_wizard/` never imports `paho`/`mqtt`. This means every install of the `checkmk-wizard` console script pulls in a dependency it never uses, purely because the test suite and dev-side `uv run` execution of `scripts/mqtt_poller.py`/`scripts/smoke_test_poller.py` need it.
**Fix:** Move `paho-mqtt` to `[dependency-groups] dev` alongside `pytest`/`pytest-asyncio`/`respx`, consistent with the "standalone script" boundary the module docstring itself asserts, and rely on the poller's own `pip install --no-cache-dir paho-mqtt==2.1.0` at container start (already done in `deploy/compose.yaml`) for the deployed runtime.

### WR-05: `check_ghost_tombstone` can permanently pollute the live retained topology if the restart command fails

**File:** `scripts/smoke_test_poller.py:342-394`
**Issue:** `check_ghost_tombstone` publishes a synthetic ghost node onto the **live** retained `lan/devices/topology` topic (`ghost_payload`, retained, `qos=1`) before attempting to restart the poller:
```python
info = client.publish(mqtt_poller.TOPIC_TOPOLOGY, ghost_payload, qos=1, retain=True)
...
result = subprocess.run(shlex.split(restart_cmd), cwd=compose_dir, capture_output=True, text=True, check=False)
if result.returncode != 0:
    print(f"[FAIL] ghost_tombstone: restart command failed:\n...")
    return False
```
If `restart_cmd` fails (wrong `--compose-dir`, `podman` not on `PATH`, container name mismatch, etc.), the function returns `False` immediately without ever restarting the poller and without restoring the original topology payload it captured just beforehand (`data`). Since the poller was never actually restarted, its next successful cycle won't self-correct this either (nothing changed to trigger a topology republish for `smoketest-ghost` alone, since it's already present) — the ghost device is left retained on a real deployment's broker indefinitely, corrupting the topology every consumer sees, purely because a *test helper's* subprocess call failed.
**Fix:** On `restart_cmd` failure, republish the original captured topology payload (`client.publish(mqtt_poller.TOPIC_TOPOLOGY, payload, qos=1, retain=True)`) before returning `False`, to restore prior state regardless of the smoke test's own outcome.

### WR-06: `--once` mode leaves a stale "online" heartbeat after it exits

**File:** `scripts/mqtt_poller.py:887-910`
**Issue:** Same root cause as CR-02 but on the successful `--once` completion path: after `run_cycle(...)`, the script calls `client.loop_stop(); client.disconnect()` without republishing `{"status": "offline"}`. Anyone running `uv run python scripts/mqtt_poller.py --once` for manual verification against a live broker (as the deployment doc's §7 suggests for diagnostics) leaves the retained `lan/poller/status` topic reporting "online" with a real (but now stale) `last_poll`, until either the real `poller` service overwrites it or a downstream staleness check eventually ages it out.
**Fix:** Same as CR-02's suggested `_shutdown()` helper — call it here too so `--once` behaves like a real, honest graceful stop.

### WR-07: `derive_folder()` matches the *first* `"wato"` path segment, which breaks if the Checkmk site ID is itself `"wato"`

**File:** `scripts/mqtt_poller.py:282-297`
**Issue:** `derive_folder()` uses `parts.index("wato")`, which returns the index of the *first* occurrence of `"wato"` in the split path. A Livestatus `filename` column value has the shape `/omd/sites/<SITE_ID>/etc/check_mk/conf.d/wato/<folder>/hosts.mk`. If `<SITE_ID>` happens to be `wato` (a valid, if unusual, OMD site name), `parts.index("wato")` matches the site-name segment instead of the real WATO config-root segment, and the derived "folder" ends up including `etc/check_mk/conf.d/wato/...` instead of the actual folder path. This is a low-probability but real edge case with no test coverage.
**Fix:** Search from the end (`parts[::-1].index("wato")`-style, or locate the specific `conf.d/wato` two-segment anchor) rather than the first occurrence, since the real WATO config root is always the *last* `wato` segment in a well-formed path.

## Info

### IN-01: `keepalive=30` is duplicated across two MQTT client constructions

**File:** `scripts/mqtt_poller.py:490`, `scripts/mqtt_poller.py:678`
**Issue:** The same magic number `30` (keepalive seconds) is repeated in `build_mqtt_client()` and `reconcile_state()` rather than being a named module constant.
**Fix:** Optionally hoist to a constant, e.g. `_MQTT_KEEPALIVE_SECONDS = 30`, for a single source of truth.

### IN-02: Default credentials shipped in `deploy/compose.yaml`

**File:** `deploy/compose.yaml:22-23,66-67,149-150`
**Issue:** `CMK_PASSWORD=cmkadmin`, `MINIO_ROOT_PASSWORD=minioadmin`, and `MQTT_USERNAME=poller`/`MQTT_PASSWORD=poller` are checked-in defaults, and MQTT/Checkmk/MinIO ports are published to the LAN. This is already clearly documented as an intentional, disposable dev/local default with a rotation script (`deploy/gen-mosquitto-passwd.sh`) and an explicit "rotate ... before exposing this stack beyond a trusted LAN" warning in the accompanying doc, so this is informational only, not a defect.
**Fix:** None required beyond what's already documented; noted here for completeness of the security scan.

---

_Reviewed: 2026-09-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
