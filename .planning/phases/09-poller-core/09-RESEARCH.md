# Phase 9: Poller Core - Research

**Researched:** 2026-09-06
**Domain:** Checkmk Livestatus polling + MQTT retained-state publishing (Python standalone daemon)
**Confidence:** HIGH (paho-mqtt 2.1.0 API — verified directly against the installed package source; MQTT retain/LWT semantics; existing repo patterns) / MEDIUM (exact Livestatus `hosts` table column set — verified for some columns against official docs/werks, ASSUMED for others pending live `GET columns` check) / MEDIUM (reconciliation strategy — original design reasoning, not live-load-tested)

## Summary

Phase 9 builds a long-running Python poller that queries Checkmk Livestatus once per cycle, computes per-device status/topology, and publishes retained MQTT messages per the fixed topic contract. The core engineering problem this research resolves — flagged explicitly by CONTEXT.md and SUMMARY.md as needing a dedicated pass — is **how a poller with "no persisted state of its own"** (the phase's own success-criteria language) can still (a) avoid a false republish storm on restart, (b) correctly tombstone a host that was deleted from Checkmk *while the poller itself was down*, and (c) avoid a spurious burst of fake state-transition history entries on its very first cycle after starting.

The resolved strategy (superseding `ARCHITECTURE.md`'s original checkpoint-file recommendation, which predates the locked "standalone script, no persisted state" decision in `09-CONTEXT.md`): on startup, the poller subscribes to the single retained `lan/devices/topology` topic and waits a short bounded timeout for the one retained message Mosquitto will deliver immediately on SUBACK. This reconstructs "previously known device IDs + parent structure" from the broker's own persistent store — not a poller-owned file — which is exactly what "no persisted state of its own" means in practice: state recovery is delegated entirely to Mosquitto's `persistence true` (already delivered in Phase 8), not duplicated locally. Because it's a *single* retained topic (not a wildcard subscription across N per-device topics), there's no non-deterministic "how long do I wait for all retained messages to arrive" problem — the exact issue that made `ARCHITECTURE.md` reject broker-side rehydration for the per-device case. Per-device status/history reconciliation is deliberately **not** attempted this way: the status topic is self-correcting every poll cycle regardless (no reconciliation needed), and history/events simply suppress transition-logging for one cycle after any restart (an accepted, self-correcting, bounded-log cosmetic gap, exactly as `PITFALLS.md` Pitfall 2 already sanctions).

The existing codebase already contains a fully worked, live-verified example of the exact paho-mqtt 2.1.0 v2-callback-API pattern this poller needs (`scripts/smoke_test_broker.py`, built in Phase 8) — including LWT semantics, retained-message publish, and threaded connect/subscribe with bounded waits. This phase should follow that file's idioms directly rather than re-deriving them from generic paho-mqtt docs.

**Primary recommendation:** A single standalone script `scripts/mqtt_poller.py` (matching the `scripts/smoke_test_broker.py` precedent — portable, no `checkmk_wizard` package import, only stdlib + `paho-mqtt`), run as a new dedicated `poller` compose service bind-mounting the git-tracked `scripts/` directory (not the untracked `./app` dir), reconciling "previously known topology" from the broker's single retained `lan/devices/topology` topic on startup instead of any local checkpoint file.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Packaging & Launch**
- **D-01:** The poller is a **standalone script**, not a module inside the installable `checkmk_wizard` package — it must run independently of the wizard and be deployable to sites where the wizard isn't needed/installed. Do not add it as `src/checkmk_wizard/*.py` or wire it into the `checkmk-wizard` console script.
- **D-02:** The poller gets its own **dedicated `poller` compose service** in `deploy/compose.yaml` (not reusing the `worker` container's idle `tail -f /dev/null` process), with `restart: unless-stopped` for automatic crash recovery independent of the worker container's interactive wizard usage.

**Poll Interval & Configuration**
- **D-03:** Default poll interval is **60 seconds**.
- **D-04:** All poller runtime settings are configured via **environment variables** on the new `poller` compose service — same pattern as `worker`'s existing `MQTT_HOST`/`MQTT_PORT`. At minimum: poll interval, MQTT broker host/port/credentials (the `poller` user from `deploy/mosquitto.passwd`/`deploy/mosquitto.acl`), and Livestatus host/port.

**History/Events Retention Bounds**
- **D-05:** `lan/devices/{id}/history` is capped by `HISTORY_MAX_ENTRIES`, **default 20**.
- **D-06:** `lan/events/recent` is capped by `EVENTS_MAX_ENTRIES`, **default 50**.

**Status Payload Shape**
- **D-07:** Downtime/acknowledgement fields are named **`in_downtime`** and **`acknowledged`** — mirroring Livestatus's own column naming (`scheduled_downtime_depth > 0` → `in_downtime`, `acknowledged` → `acknowledged`).
- **D-08:** Overall per-host status is computed via **worst-of aggregation across the host and all its services** (CRIT beats WARN beats UNKNOWN beats OK; a host-level DOWN/UNREACHABLE always wins outright) — preserves PLR-03's OK/WARN/CRIT/UNKNOWN/DOWN granularity.

### Claude's Discretion
- Exact script filename/location and internal module layout (dataclasses, typed exceptions, no silent broad `except`, `from __future__ import annotations`)
- Exact env var names beyond those specified (e.g. `MQTT_USERNAME`, `MQTT_PASSWORD`, `LIVESTATUS_HOST`, `LIVESTATUS_PORT`, `POLL_INTERVAL_SECONDS`)
- Restart/reconciliation strategy (RESOLVED below — this is the research pass SUMMARY.md flagged as needed)
- Per-topic QoS choices (research recommends QoS 0 for the every-cycle status topic, QoS 1 for change-only topics: topology/tombstones/history/events)
- Exact JSON payload field layout beyond the named fields above
- Whether/how the poller reads a `device_type` tag (must be defensive with a safe default, since the tag doesn't exist until Phase 10)

### Deferred Ideas (OUT OF SCOPE)
- Device-type tagging in the wizard's onboarding flow — already scoped as Phase 10 (TAG-01/02/03). This phase's poller reads the resulting tag defensively with a safe `"unknown"` default; assigning the tag itself is Phase 10's job, not this phase's.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLR-01 | Poller connects to Livestatus over TCP on a configurable interval and queries host state, service-state summary, tags, parent/folder info | Resolved LQL query shape (single `GET hosts` call, `OutputFormat: json`) below in Architecture Patterns; existing `livestatus.py` one-shot connect/query/close pattern extended, not replaced |
| PLR-02 | Diffs against Livestatus's live current state each cycle, not in-memory history — self-heals across restarts, no persisted state required | Resolved reconciliation strategy (subscribe to single retained `lan/devices/topology` topic on startup) — see "Restart/Reconciliation Strategy (Resolved)" below |
| PLR-03 | Publishes per-device retained status every cycle, preserving OK/WARN/CRIT/UNKNOWN/DOWN granularity + timestamp | Worst-of aggregation formula resolved below; status payload schema in Code Examples |
| PLR-04 | Publishes `lan/devices/topology` only when topology actually changes | Topology-diff algorithm below (compare id+parents structure cycle-to-cycle) |
| PLR-05 | Publishes bounded per-device history + bounded global events feed, transition-only | Bounded-list-replace pattern (Pitfall 6-consistent) in Code Examples |
| PLR-06 | Publishes empty/tombstone retained payloads for removed devices | Tombstone mechanics (zero-length retained publish) verified against MQTT spec + existing `scripts/smoke_test_broker.py`'s own `_cleanup()` precedent |
| PLR-07 | Birth/LWT liveness signal on `lan/poller/status` | `will_set()`/`on_connect` pattern verified against installed paho-mqtt 2.1.0 source; recommend adding a per-cycle heartbeat refresh (see Common Pitfalls) |
| PLR-08 | Surfaces downtime/acknowledgement state | `scheduled_downtime_depth`/`acknowledged` Livestatus columns, mapped to `in_downtime`/`acknowledged` per D-07 |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Livestatus polling & state computation | API/Backend (poller process) | — | The poller is the only component that talks to Livestatus; pure backend logic, no UI |
| Worst-of status aggregation (host + services) | API/Backend (poller process) | — | Business logic deciding "what does this device's state mean" belongs with the data producer, not the broker or dashboard |
| Per-device/topology/history/events MQTT publish | API/Backend (poller process) | Database/Storage (Mosquitto retained store) | Poller decides *what* and *when* to publish; Mosquitto's `persistence true` is what actually survives restarts — the poller intentionally owns no persistence layer of its own |
| Startup reconciliation (topology-topic subscribe) | API/Backend (poller process) | Database/Storage (Mosquitto retained store) | The "previous state" the poller reconciles against lives in Mosquitto's retained store, read once at startup — this is the mechanism that satisfies "no persisted state of its own" |
| Tombstone publishing on host removal | API/Backend (poller process) | — | Detecting removal requires comparing live Livestatus data against the reconciled previous ID set — inherently a backend/data-layer decision |
| Poller liveness (birth/LWT) | API/Backend (poller process) | Database/Storage (Mosquitto retained store + broker-native LWT delivery) | The LWT payload itself is stored and delivered by Mosquitto on ungraceful disconnect — the poller only *configures* it once at connect time |
| MQTT credential/ACL enforcement | Database/Storage (Mosquitto ACL) | — | Already delivered in Phase 8; this phase only consumes the existing `poller` user's credentials, does not re-implement access control |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `paho-mqtt` | 2.1.0 `[VERIFIED: installed in .venv]` | MQTT publisher client | Already a project dependency (`pyproject.toml`, added in Phase 8 per D-08); Eclipse Foundation's reference Python MQTT client; already used correctly (v2 `CallbackAPIVersion`) in `scripts/smoke_test_broker.py` |
| Python stdlib `socket` | stdlib | Livestatus TCP client | Matches existing `src/checkmk_wizard/livestatus.py` one-shot connect/query/close pattern exactly — extend the query, not the transport mechanism |
| Python stdlib `json` | stdlib | Livestatus `OutputFormat: json` response parsing + MQTT payload serialization | JSON output format natively nests Livestatus's dict/list-typed columns (`tags`, `parents`) as proper JSON structures — far simpler and more robust than hand-parsing CSV's custom `Separators:` header for those column types. `[CITED: docs.checkmk.com/latest/en/livestatus.html]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `dataclasses` | stdlib | `PollerConfig`, device/topology records | Matches every other module in this codebase's convention |
| Python stdlib `datetime` (`datetime.UTC`) | stdlib | Status payload timestamps | Matches `wizard.py`'s existing `datetime.UTC` convention (Python 3.11+) |
| Python stdlib `logging` | stdlib | Poll-cycle/error logging | No new dependency needed; avoid printing MQTT credentials to logs (see Security Domain) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single-file standalone script | A local `scripts/poller/` package (multiple modules) | Only worth it if the single file exceeds ~600-800 lines and internal organization genuinely suffers; D-01's portability requirement is satisfied either way (a directory copies just as easily as a file) but a single file is simpler to reason about and matches the `scripts/smoke_test_broker.py` precedent already in this repo |
| Livestatus `OutputFormat: json` | `OutputFormat: csv` with a custom `Separators:` header | CSV works but requires manually parsing nested list/dict columns (`tags`, `parents`) using non-default ASCII separator codes — more code, more edge cases, no upside since `json` is equally supported and stdlib `json.loads()` handles it for free |
| Startup reconciliation via single retained topology topic | A local checkpoint file (`ARCHITECTURE.md`'s original recommendation) | Rejected — contradicts this phase's explicit "no persisted state of its own required" success criterion; also `./app` (the bind-mount ARCHITECTURE.md assumed) does not exist in this repo (see Common Pitfalls) |
| Startup reconciliation via single retained topology topic | Re-subscribing to wildcard `lan/devices/+/status` on startup | Rejected by `ARCHITECTURE.md` itself for good reason — no deterministic "all retained messages have arrived" signal across potentially many per-device topics. A *single* topology topic sidesteps this entirely (one SUBACK, one message, done) |

**Installation:** No new packages required — `paho-mqtt>=2.1.0` is already a dependency (added in Phase 8, `pyproject.toml`). Verify at any time with:
```bash
uv run python -c "import importlib.metadata as md; print(md.version('paho-mqtt'))"
# → 2.1.0 (confirmed installed in this repo's .venv during this research pass)
```

## Package Legitimacy Audit

No new external packages are introduced by this phase. `paho-mqtt` was already vetted and added to `pyproject.toml` during Phase 8 (D-08), and this research pass directly confirmed it is installed at the exact version (`2.1.0`) that `STACK.md` recommended.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| paho-mqtt | PyPI | Eclipse Foundation project, multi-year history | Very high (standard MQTT client) | github.com/eclipse-paho/paho.mqtt.python | Not re-run (no new install) | Approved — already vetted in Phase 8, confirmed installed at 2.1.0 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
[poll timer fires, every POLL_INTERVAL_SECONDS]
        |
        v
[poller: one-shot TCP connect to checkmk:6557 (Livestatus)]
        |
        v  GET hosts / Columns: name state scheduled_downtime_depth
        |  acknowledged worst_service_state parents tags filename
        |  OutputFormat: json
[poller: parse JSON rows -> list of raw host records]
        |
        v
[poller: compute per-device status]           (D-08 worst-of aggregation:
        |                                       host DOWN/UNREACHABLE always
        |                                       wins; else worst_service_state)
        |
        +---------------------+----------------------------+
        v                     v                             v
[publish status]     [compute topology from all rows]  [compare device-ID set
 every cycle,          (id + parents + device_type)      vs previous cycle's]
 QoS0 retain=True             |                                |
        |                     v                                v
        |          [diff vs previous topology]        [ids removed since
        |           in-memory var]                      last cycle or since
        |                     |                          startup reconcile]
        |            changed? |  unchanged? no publish        |
        |                     v                                v
        |          [publish topology,             [publish empty (tombstone)
        |           QoS1 retain=True]               payload to that id's
        |                                            status + history topics,
        |                                            QoS1 retain=True; remove
        |                                            from topology + append
        |                                            "removed" event]
        v
[compute per-device transition (old state -> new state), skip
 on the cycle immediately following process start]
        |
        v
[append to bounded history[id] (max HISTORY_MAX_ENTRIES) and
 bounded events (max EVENTS_MAX_ENTRIES); publish full replaced
 arrays, QoS1 retain=True]
        |
        v
[sleep until next cycle]

--- Startup (once, before the loop above begins) ---
[poller connects to Mosquitto, will_set() configured BEFORE connect()]
        |
        v
[on_connect: publish lan/poller/status = {"status":"online",...}, QoS1 retain]
        |
        v
[subscribe lan/devices/topology (QoS1), wait up to RECONCILE_TIMEOUT_SECONDS
 for the one retained message Mosquitto delivers on SUBACK]
        |
   message arrived?              no message within timeout?
        |                                   |
        v                                   v
[parse into previous_topology       [previous_topology = {} — cold start;
 dict: {id: {parents, ...}}]         first cycle publishes everything as
        |                             "new" but logs no false transitions]
        v
[enter main poll loop above, using previous_topology as cycle-0 baseline]
```

Two independent failure surfaces this handles correctly by construction:
1. **Poller crashes and restarts** — `previous_topology` is rebuilt from Mosquitto's own retained store (already durable per Phase 8's `persistence true`), not from anything the poller itself wrote to disk.
2. **A host is deleted from Checkmk while the poller is down** — because reconciliation restores the previously-known device-ID set (not just an empty set), the very first post-restart cycle correctly notices the missing ID and tombstones it, rather than silently never knowing it needs to.

### Recommended Project Structure
```
scripts/
├── smoke_test_broker.py      # existing (Phase 8) — same "standalone,
│                              # not pytest-collected, not in src/" pattern
└── mqtt_poller.py             # NEW — this phase's deliverable, single
                                # file for portability (D-01); split into
                                # scripts/poller/ only if it grows unwieldy

deploy/
└── compose.yaml                # gains a new `poller` service (see below)
```

**Why not `src/checkmk_wizard/mqtt_poller/` (ARCHITECTURE.md's original suggestion):** that recommendation predates D-01's explicit lock. D-01's own stated reasoning — "it must run independently of the wizard and be deployable to a site where the wizard isn't needed/installed" — rules out anything importing from the installable `checkmk_wizard` package, since that would require the package (and therefore the wizard, `uv`, `pyproject.toml`) to exist at the target site. `scripts/` already establishes the "standalone, portable, not part of the package" location in this exact repo (`smoke_test_broker.py`), so this phase extends that precedent rather than inventing a new one.

### Pattern 1: Single-topic startup reconciliation (resolves PLR-02's "no persisted state" requirement)

**What:** Subscribe once, at startup, to the single retained `lan/devices/topology` topic (not a wildcard across per-device topics) and use a bounded wait (`threading.Event` + timeout) to capture the one retained message Mosquitto delivers immediately on SUBACK, mirroring `scripts/smoke_test_broker.py`'s own `_wait_for_retained_payload()` helper.
**When to use:** Any time a "no local persisted state" daemon needs to recover a prior snapshot from a durable broker rather than its own filesystem.
**Example:**
```python
# Source: pattern adapted from scripts/smoke_test_broker.py's
# _wait_for_retained_payload() (this repo, Phase 8, live-tested)
import json
import threading

import paho.mqtt.client as mqtt

def reconcile_topology(host: str, port: int, user: str, password: str,
                        timeout: float) -> dict[str, dict]:
    """Return the previously-published topology, or {} on cold start."""
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
        client.subscribe("lan/devices/topology", qos=1)
        client.loop_start()
        if not received.wait(timeout=timeout) or not payloads[0]:
            return {}  # cold start: never published before, or tombstoned
        data = json.loads(payloads[0].decode())
        return {node["id"]: node for node in data.get("devices", [])}
    finally:
        client.loop_stop()
        client.disconnect()
```

### Pattern 2: Livestatus one-shot JSON query covering host + service-summary + tags + parents + downtime/ack in one call

**What:** A single `GET hosts` query per cycle requesting all needed columns at once (no per-service or per-host follow-up queries), using `OutputFormat: json` so list/dict-typed columns (`tags`, `parents`) parse as native Python structures via `json.loads()` instead of hand-parsed CSV.
**When to use:** Every poll cycle — this is the only Livestatus interaction the poller needs.
**Example:**
```python
# Source: extends src/checkmk_wizard/livestatus.py's existing one-shot
# connect/send/read-until-EOF pattern; column names verified per
# docs.checkmk.com/latest/en/livestatus.html (json OutputFormat) and
# checkmk.com/werk/8003 (worst_service_state) / werk/7761 (tags column).
# `parents` and `filename` column names are ASSUMED from training
# knowledge + this project's own existing use of `filename`-derived
# folder paths (site.py) — verify with a live `GET columns` query
# (see Common Pitfalls) before considering this query final.
import json
import socket

LIVESTATUS_QUERY = (
    "GET hosts\n"
    "Columns: name state scheduled_downtime_depth acknowledged "
    "worst_service_state parents tags filename\n"
    "OutputFormat: json\n"
    "\n"
)

def query_hosts(host: str, port: int, timeout: float = 10) -> list[list]:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(LIVESTATUS_QUERY.encode())
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    text = b"".join(chunks).decode(errors="replace")
    return json.loads(text) if text.strip() else []
    # Each row: [name, state, scheduled_downtime_depth, acknowledged,
    #            worst_service_state, parents, tags, filename]
    # `parents` -> JSON array of parent host names (e.g. ["switch-01"])
    # `tags`    -> JSON object (e.g. {"tag_device_type": "unknown", ...})
```

### Pattern 3: Worst-of status aggregation (D-08, resolved mapping)

**What:** Collapse host state + worst service state into exactly the 5 values PLR-03 requires: `OK`, `WARN`, `CRIT`, `UNKNOWN`, `DOWN`.
**Resolved mapping:**
```python
# host state: 0=UP, 1=DOWN, 2=UNREACHABLE (existing convention,
# src/checkmk_wizard/livestatus.py docstring)
# worst_service_state: 0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN (standard Nagios
# plugin return codes, used unchanged by Checkmk/Livestatus)
_SERVICE_STATE_NAMES = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}

def compute_overall_state(host_state: int, worst_service_state: int) -> str:
    if host_state != 0:  # DOWN (1) or UNREACHABLE (2) both collapse to DOWN —
        return "DOWN"     # PLR-03 lists exactly 5 states, not 6; D-08 confirms
                            # "host-level DOWN/UNREACHABLE always wins outright"
    return _SERVICE_STATE_NAMES.get(worst_service_state, "UNKNOWN")
```

### Pattern 4: Bounded history/events — full-array replace, never append client-side

**What:** Every publish to `lan/devices/{id}/history` or `lan/events/recent` sends the *complete* bounded list (already truncated to `HISTORY_MAX_ENTRIES`/`EVENTS_MAX_ENTRIES`), not a delta. This is what lets Pitfall 6 (unbounded browser memory growth) be fully solved on the publisher side — the future dashboard just needs to *replace*, never append.
```python
def append_bounded(history: list[dict], entry: dict, max_entries: int) -> list[dict]:
    return (history + [entry])[-max_entries:]
```

### Anti-Patterns to Avoid
- **Per-device Livestatus queries in a loop:** Use one `GET hosts` query for all devices per cycle (Pattern 2) — a per-host query loop makes poll-cycle time grow linearly with fleet size (documented Performance Trap in `PITFALLS.md`).
- **Treating a poller restart as "everything changed":** Without reconciliation (Pattern 1), a naive implementation would either stay silent (never notices Checkmk changed during downtime) or blast a full republish storm. Neither is correct — see Pattern 1.
- **CSV `OutputFormat` for this query:** Works for the existing 2-scalar-column `query_host_states()` but becomes needlessly fragile once `tags`/`parents` (dict/list columns) enter the column list — use `json` instead (Pattern 2).

## Restart/Reconciliation Strategy (Resolved)

This is the specific open question `09-CONTEXT.md` and `SUMMARY.md`'s Research Flags called out as needing a dedicated pass. Resolution:

1. **Do NOT use a local checkpoint file.** `ARCHITECTURE.md`'s original recommendation assumed a bind-mounted `./app` directory the poller could write to — but D-01 locks the poller as a standalone script with "no persisted state of its own required" (this phase's own success-criteria language), and separately, `./app` **does not exist in this repo** (it's referenced by `worker`'s compose service but never created/committed — see Common Pitfalls). Both the phase's explicit intent and the concrete filesystem reality rule this option out.
2. **Do NOT reconcile via wildcard subscription to all `lan/devices/+/status` topics.** `ARCHITECTURE.md` already correctly identified the problem: MQTT has no "end of retained backlog" signal, so with N per-device topics you can't deterministically know when you've received them all.
3. **DO reconcile via a single subscription to `lan/devices/topology`.** Because this is exactly one retained topic, Mosquitto delivers exactly one message (or none, on cold start) immediately after SUBACK — no ambiguity, no arbitrary "wait and hope" heuristic beyond a simple bounded timeout for the "never published before" case. Parse it into `previous_topology: dict[id, {parents, device_type, ...}]` and use that as cycle-0's diff baseline for both topology-change detection (PLR-04) and tombstone detection (PLR-06) — including hosts deleted from Checkmk *while the poller was down*, which a naive empty-baseline restart would silently miss.
4. **Per-device status/history is NOT reconciled, by design, and this is fine.** The `status` topic is republished fresh every cycle from live Livestatus data regardless (PLR-03), so it needs no "previous" value at all. History/events genuinely cannot know a "from" state on the very first cycle after any restart — suppress transition-logging for exactly that one cycle (matches the already-accepted "cosmetic, bounded, self-correcting" edge case documented in `PITFALLS.md` Pitfall 2), then resume normal transition detection from cycle 2 onward using the poller's own in-memory `last_status` dict (which only needs to survive within a single process's uptime, not across restarts).

This design satisfies every stated success criterion: status is always live-Livestatus-correct (criterion 1/2), topology republishes only on genuine change including the reconciled restart case (criterion 3), and deleted hosts get tombstoned within one cycle whether the poller was up or down at deletion time (criterion 4) — all without the poller owning a single byte of its own persisted state.

## Topic Contract (Resolved QoS/Retain Table)

| Topic | Publish Trigger | QoS | Retain | Payload |
|-------|-----------------|-----|--------|---------|
| `lan/devices/{id}/status` | Every poll cycle, every known device | 0 | true | `{"state": "OK\|WARN\|CRIT\|UNKNOWN\|DOWN", "timestamp": "<ISO8601 UTC>", "in_downtime": bool, "acknowledged": bool}` |
| `lan/devices/topology` | Only when the id+parents+device_type structure changes vs. previous cycle | 1 | true | `{"devices": [{"id": str, "parents": [str, ...], "device_type": str}, ...], "timestamp": "<ISO8601 UTC>"}` |
| `lan/devices/{id}/history` | Only on an actual state transition for that device | 1 | true | Full bounded array (max `HISTORY_MAX_ENTRIES`): `[{"timestamp": ..., "from": "OK", "to": "CRIT"}, ...]` |
| `lan/events/recent` | Only on any device's state transition, or a device add/remove | 1 | true | Full bounded array (max `EVENTS_MAX_ENTRIES`): `[{"timestamp": ..., "device_id": str, "event": "state_change\|added\|removed", "from": str \| null, "to": str \| null}, ...]` |
| `lan/devices/{id}/status` (tombstone) | Device disappears from Livestatus's `GET hosts` result | 1 | true | Empty payload (`b""` / `payload=None`) |
| `lan/devices/{id}/history` (tombstone) | Same cycle as the status tombstone | 1 | true | Empty payload |
| `lan/poller/status` (birth) | Once, in `on_connect` | 1 | true | `{"status": "online", "since": "<ISO8601 UTC>"}` |
| `lan/poller/status` (heartbeat) | Every poll cycle (recommended addition — see Common Pitfalls) | 1 | true | `{"status": "online", "since": "<original connect time>", "last_poll": "<ISO8601 UTC>"}` |
| `lan/poller/status` (LWT/death) | Configured via `will_set()` before `connect()`; broker sends it on ungraceful disconnect | 1 | true | `{"status": "offline"}` |

**Note on the QoS choice for `history`/`events`:** `PITFALLS.md` Pitfall 7 originally reasoned QoS 0 is defensible for `lan/events/recent` specifically (self-correcting on the next event). This research recommends QoS 1 uniformly for every change-only topic instead — simpler mental model ("continuous = QoS 0, change-triggered = QoS 1, no exceptions"), consistent with what `09-CONTEXT.md`'s own discretion note already paraphrases ("QoS 1 for change-only topics: topology/tombstones/history/events"), and the reliability cost of QoS 1 on a low-frequency topic is negligible.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MQTT reconnect/backoff | A custom retry loop around `socket`/manual reconnect | `paho-mqtt`'s `Client.loop_start()` + `reconnect_delay_set(min_delay=1, max_delay=120)` (verified defaults from installed source, `client.py:1533`) | Already the exact pattern `scripts/smoke_test_broker.py` uses; re-deriving it risks missing edge cases (e.g. exponential backoff cap) the library already handles |
| "Clear a retained topic" | A special "delete" message type/convention | Publish a zero-length payload with `retain=True` (MQTT spec-defined tombstone semantics) | This exact mechanism is already used in this repo's `scripts/smoke_test_broker.py::_cleanup()` (`client.publish(topic, payload=None, retain=True)`) — proven to work against the real deployed broker in Phase 8 |
| Livestatus dict/list column parsing | Custom CSV `Separators:`-header parsing for `tags`/`parents` | `OutputFormat: json` + stdlib `json.loads()` | Livestatus already serializes dict/list columns as native JSON structures when asked; hand-parsing CSV's positional ASCII separators for nested data is strictly more code for zero benefit |
| Livestatus connection resilience | A dedicated backoff/retry state machine for Livestatus TCP errors | Let the poll interval itself be the retry delay — one failed cycle (`OSError`/`TimeoutError`) just logs and skips to next cycle | Exactly `ARCHITECTURE.md` Pattern 4's reasoning; a 60s poll interval already acts as backoff, no separate state machine needed |

**Key insight:** Every "hard part" of this phase (reconnect, tombstone-via-empty-retain, resilient polling) already has either a library-provided mechanism (`paho-mqtt`) or a working, live-tested precedent in this exact repo (`scripts/smoke_test_broker.py`, Phase 8). The only genuinely new design work is the reconciliation strategy above — everything else is composition of already-proven pieces.

## Common Pitfalls

### Pitfall A: `./app` bind mount referenced in `deploy/compose.yaml` does not exist in this repo
**What goes wrong:** `worker`'s compose service already declares `volumes: - ./app:/app:z` (relative to `deploy/`, i.e. `deploy/app/`), but this directory is not committed to git and does not exist on a fresh checkout. If the planner assumes the poller can simply be "placed in `./app`" (as `ARCHITECTURE.md`'s original checkpoint-file discussion implicitly did), the deployment step silently has no script to run.
**Why it happens:** `./app` is treated as an ad hoc, host-created working directory for the `worker` container (not source-controlled), which is fine for that container's interactive/manual use but wrong for a `restart: unless-stopped` service that must run unattended from first boot.
**How to avoid:** Bind-mount the git-tracked `scripts/` directory directly into the new `poller` service (e.g. `../scripts:/scripts:ro,z`, relative to `deploy/compose.yaml`) so the poller script ships with the repo and requires no manual copy step to a host-created, non-tracked directory.
**Warning signs:** `podman compose up poller` fails with "no such file or directory" for the poller's entrypoint script.

### Pitfall B: MQTT topic injection via unsanitized Checkmk host names
**What goes wrong:** Device IDs are interpolated directly into topic strings (`lan/devices/{id}/status`). MQTT reserves `+` and `#` as wildcard characters and treats `/` as a topic-level separator. A Checkmk host onboarded outside this project's own wizard (e.g. created directly via the Checkmk UI, or via `bulk_create_hosts` with an unusual name) could contain any of these characters, silently corrupting the topic hierarchy (e.g. a host named `lan/rogue` would publish into a nested, unintended topic branch; a host containing `#` could behave unpredictably against some broker/client combinations).
**Why it happens:** The wizard's own onboarding flow already validates hostnames (`_HOSTNAME_RE` in `wizard.py`), but Livestatus reports *all* hosts known to Checkmk, including ones never onboarded through this project's wizard.
**How to avoid:** Validate/reject (or sanitize, e.g. replace `/`, `+`, `#` with `_`) any host name before using it to build a topic string. Log a warning and skip publishing for any host whose name fails this check, rather than silently corrupting the topic tree.
**Warning signs:** `mosquitto_sub -t 'lan/#' -v` shows unexpected nested topic branches under `lan/devices/` that don't correspond to any real device ID.

### Pitfall C: `lan/poller/status` birth-only (no heartbeat) can't detect a hung-but-connected process
**What goes wrong:** MQTT's LWT only fires on an *ungraceful disconnect* (TCP connection actually drops). If the poller's poll loop deadlocks or an unhandled exception silently kills the polling thread while the MQTT network thread (`loop_start()`'s background thread) keeps the TCP connection alive, the broker never triggers the will — `lan/poller/status` stays `"online"` forever even though the poller has stopped doing anything useful. DASH-04 (Phase 11) needs to show a distinct "poller stale" state, which requires a timestamp that's actually refreshed, not just a one-time birth message.
**Why it happens:** Birth + LWT together only cover the binary "connected vs. disconnected" case, not "connected but not actually working."
**How to avoid:** Republish `lan/poller/status` with a fresh `last_poll` timestamp every cycle (not just once at connect), so a consuming dashboard can independently detect staleness via `now - last_poll > threshold`, exactly the same staleness pattern already planned for per-device status.
**Warning signs:** Dashboard shows the poller as "online" while no device status has updated for many multiples of the poll interval.

### Pitfall D: Livestatus column names not exhaustively documented — verify live before finalizing the query
**What goes wrong:** Official Checkmk docs (`docs.checkmk.com/latest/en/livestatus_references.html`) explicitly do not publish a full column-by-column reference for the `hosts` table; the documented way to get ground truth is `GET columns\nFilter: table = hosts` against a live site. This research confirmed `worst_service_state`, `acknowledged`, and `scheduled_downtime_depth` against official docs/werks, but `parents`, `tags`, and `filename` are carried forward from training knowledge and this project's own prior use (`filename` is already referenced in `ARCHITECTURE.md`'s example query and is the mechanism `site.py` uses for folder-derived data) rather than independently re-verified this session.
**Why it happens:** Checkmk's Livestatus column set has historically grown via werks (e.g. `tags`/`labels` added per Werk #7761) without a single canonical up-to-date reference page.
**How to avoid:** Before finalizing the poller's query, run `GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json` against the actual deployment's live Checkmk site (matching this project's own established "live-verify against a real Checkmk 2.4.0p35 site" convention, cited throughout `api.py`/`site.py` docstrings) and confirm every column name in `LIVESTATUS_QUERY` actually exists before shipping.
**Warning signs:** Livestatus returns an error response (e.g. `Table 'hosts' has no column 'parents'`) instead of the expected JSON rows.

## Code Examples

### MQTT client setup with birth + LWT (paho-mqtt 2.1.0, VERSION2 API)
```python
# Source: pattern verified against this repo's installed paho-mqtt 2.1.0
# source (.venv/lib/python3.11/site-packages/paho/mqtt/client.py) and
# scripts/smoke_test_broker.py's live-tested usage (Phase 8).
from __future__ import annotations

import datetime
import json

import paho.mqtt.client as mqtt

POLLER_STATUS_TOPIC = "lan/poller/status"

def build_mqtt_client(host: str, port: int, user: str, password: str) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    # will_set() MUST be called before connect() — verified in installed
    # source docstring ("This must be called before connect() to have
    # any effect.")
    client.will_set(
        POLLER_STATUS_TOPIC,
        payload=json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    def on_connect(client, userdata, flags, reason_code, properties=None):
        since = datetime.datetime.now(datetime.UTC).isoformat()
        client.publish(
            POLLER_STATUS_TOPIC,
            json.dumps({"status": "online", "since": since}),
            qos=1,
            retain=True,
        )

    client.on_connect = on_connect
    client.reconnect_delay_set(min_delay=1, max_delay=120)  # library defaults,
                                                              # confirmed from
                                                              # installed source
    client.connect(host, port, keepalive=30)
    client.loop_start()  # background thread — main thread runs the poll timer
    return client
```

### Tombstone publish (empty retained payload)
```python
# Source: same mechanism as scripts/smoke_test_broker.py's _cleanup()
def tombstone_device(client: mqtt.Client, device_id: str) -> None:
    for suffix in ("status", "history"):
        info = client.publish(f"lan/devices/{device_id}/{suffix}", payload=None, retain=True, qos=1)
        info.wait_for_publish(timeout=5)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `docs/src/mqtt_publisher_changes.py`'s v1 paho-mqtt callback API (`mqtt.Client()` with no `callback_api_version`) | `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)` with 5-arg `on_connect(client, userdata, flags, reason_code, properties)` | paho-mqtt 2.0 (already adopted in this repo's `scripts/smoke_test_broker.py`, Phase 8) | This phase must follow the v2 pattern already established in-repo, not the older prototype scripts under `docs/src/` |
| Full-blob retained topic (`checkmk/services/all`) | Per-entity retained topics (`lan/devices/{id}/status`) | Already decided at the project/PROJECT.md level, before this phase | Not this phase's decision to make — already locked upstream |

**Deprecated/outdated:**
- `docs/src/mqtt_publisher_changes.py` / `mqtt_notify.py`: reference-only prototypes using the v1 paho-mqtt callback API and full-blob retained publishing — explicitly **not** part of the installable package (per repo CLAUDE.md) and must not be copied forward as-is.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Livestatus `hosts` table exposes a `parents` column returning a JSON array of parent host names under `OutputFormat: json` | Architecture Patterns / Pattern 2 | If the column name or shape differs, the topology-parent-link derivation (PLR-01, PLR-04) silently returns wrong/empty data — must be caught by the live `GET columns` verification step (Common Pitfalls, Pitfall D) before implementation is considered done |
| A2 | Livestatus `hosts` table exposes a `filename` column giving the WATO config-file path (from which folder info can be derived) | Architecture Patterns / Pattern 2 | If absent or differently named, folder/parent-child metadata passed through to the topology payload would be missing — low severity for Phase 9 (VLAN derivation itself is explicitly Phase 10's job), but affects any Phase 9 field that surfaces folder info |
| A3 | `tags` column returns a JSON object keyed by tag group id (e.g. `tag_device_type`) under `OutputFormat: json`, matching the shape referenced in one WebSearch snippet of official docs | Architecture Patterns / Pattern 2 | If the shape differs (e.g. a different key format), the Phase 10 `device_type` tag defensive-read this phase should scaffold for would need adjustment |
| A4 | A single retained message on `lan/devices/topology` will always arrive within a short bounded timeout (a few seconds) after SUBACK if one was ever previously published, with no scenario where Mosquitto delays delivery long enough to cause a false "cold start" | Restart/Reconciliation Strategy | If wrong (e.g. broker under heavy load, network hiccup at exactly startup time), the poller would treat a warm restart as a cold start — a self-correcting cosmetic issue (one wasted republish + one cycle of suppressed history), not a data-loss bug, but worth confirming empirically once a live broker is available |

**If this table is empty:** N/A — see entries above; none of these block planning, all are cheap to verify live before/during implementation per this project's own established "live-verify against real Checkmk/Mosquitto" convention.

## Open Questions

1. **Exact Livestatus column names for `parents`/`tags`/`filename`**
   - What we know: These are long-standing, widely-referenced Livestatus columns per training knowledge and partial official-docs corroboration (Werk #7761 for `tags`, general Livestatus documentation patterns for `parents`).
   - What's unclear: No single fetched source in this research pass listed the complete, current `hosts` table column reference (Checkmk's own docs explicitly punt to a live `GET columns` query instead of a static reference page).
   - Recommendation: The planner should include a Wave 0 task that runs `GET columns\nFilter: table = hosts` against a live Checkmk 2.4.0p35 site (this project's own verification baseline) before finalizing `LIVESTATUS_QUERY`, consistent with this codebase's existing "live-verified against a real Checkmk site" documentation convention.

2. **Reconciliation timeout default value**
   - What we know: A short bounded wait (a few seconds) is architecturally sufficient since only one retained message is expected.
   - What's unclear: The exact right default (2s vs. 5s vs. 10s) depends on real broker/network latency characteristics not measurable from this sandbox (no live Mosquitto/Checkmk reachable in the research environment — see Environment Availability).
   - Recommendation: Default `RECONCILE_TIMEOUT_SECONDS=5`, configurable via env var per D-04's pattern; adjust empirically during Phase 9's own live smoke-testing (mirroring Phase 8's `scripts/smoke_test_broker.py` precedent).

## Environment Availability

| Dependency | Required By | Available (this sandbox) | Version | Fallback |
|------------|------------|---------------------------|---------|----------|
| `paho-mqtt` (Python package) | Poller MQTT client | ✓ | 2.1.0 | — |
| `podman` / `docker` | Running the live compose stack (checkmk, mosquitto, poller) for smoke-testing | ✗ (neither found in this research sandbox) | — | Live verification (Livestatus column check, reconciliation timing, tombstone-on-restart test) must happen on the actual deployment host, consistent with Phase 8's own precedent (`STATE.md` confirms Phase 8's smoke test was run "on a real deployment host", not in a sandbox) |
| `mosquitto_sub`/`mosquitto_pub` CLI | Manual topic verification during development | ✗ (not found in this research sandbox) | — | Same as above — use the deployment host, or `scripts/smoke_test_broker.py`'s own paho-mqtt-based verification pattern (no CLI dependency) |
| Live Checkmk site (Livestatus reachable) | Column verification (Open Question 1), end-to-end poller testing | ✗ (no live site in this sandbox) | — | Must be verified on the deployment host before Phase 9 is considered fully done; not a planning blocker |

**Missing dependencies with no fallback:**
- None — every gap above has a documented fallback (defer live verification to the deployment host, matching this project's own established Phase 8 pattern of a separate, non-pytest, live smoke-test script).

**Missing dependencies with fallback:**
- `podman`/`docker`, `mosquitto_sub`/`mosquitto_pub`, live Checkmk reachability — all deferred to a deployment-host smoke test, mirroring `scripts/smoke_test_broker.py`'s existing precedent.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Partial | The poller authenticates to Mosquitto with the `poller` user's credentials (already provisioned in Phase 8's `deploy/mosquitto.passwd`/`.acl`); this phase only *consumes* those credentials via env vars, does not implement auth itself |
| V3 Session Management | No | No user sessions in this phase — long-running MQTT connection managed by `paho-mqtt`'s own reconnect logic |
| V4 Access Control | Partial | Broker-side ACL enforcement (`topic readwrite #` for `poller`) was already delivered in Phase 8; this phase must not attempt to bypass or duplicate that at the application layer |
| V5 Input Validation | Yes | Livestatus response parsing (JSON) and device-ID-to-topic-string construction (see Pitfall B — MQTT topic injection via unsanitized host names) |
| V6 Cryptography | No | No new cryptography in this phase; MQTT traffic is plaintext on the internal `cmk_net` bridge network (already an accepted tradeoff per `PITFALLS.md`/`STACK.md`'s TLS discussion, not reopened here) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| MQTT topic injection via host names containing `/`, `+`, `#` | Tampering | Validate/sanitize device IDs before interpolating into topic strings (Pitfall B) |
| Credential leakage via logs (`MQTT_PASSWORD` env var accidentally logged) | Information Disclosure | Never log the full `PollerConfig` object or raw env var dump; log connection status/reason codes only, not credentials |
| Malformed/truncated Livestatus JSON response causing an unhandled parse exception that crashes the poll loop | Denial of Service | Wrap `json.loads()` in a narrow `except (json.JSONDecodeError, ValueError)`, log and skip the cycle — matches this codebase's existing pattern of narrow excepts around parse failures (`api.py:111-113`) rather than letting one bad cycle kill the whole daemon |

## Sources

### Primary (HIGH confidence)
- This repo's installed `paho-mqtt` 2.1.0 source (`.venv/lib/python3.11/site-packages/paho/mqtt/client.py`) — directly read `__init__`, `will_set()`, `publish()`, `reconnect_delay_set()` signatures and docstrings during this research session
- `scripts/smoke_test_broker.py` (this repo, Phase 8, live-tested against a real deployment host per `STATE.md`) — working VERSION2 callback API usage, LWT-adjacent reasoning, retained-message clear pattern
- `src/checkmk_wizard/livestatus.py` (this repo) — existing one-shot connect/query/close Livestatus client convention
- `deploy/compose.yaml`, `deploy/mosquitto.conf`, `deploy/mosquitto.acl`, `deploy/gen-mosquitto-passwd.sh` (this repo, Phase 8) — confirmed `poller`/`wsreader` users, ACL scoping, listener ports, and that `./app` is referenced but not committed
- [Retrieving status data via Livestatus (docs.checkmk.com)](https://docs.checkmk.com/latest/en/livestatus.html) — `OutputFormat: json` behavior, `Separators:` header behavior, query termination
- [Livestatus command reference (docs.checkmk.com)](https://docs.checkmk.com/latest/en/livestatus_references.html) — confirms no static full column list is published; `GET columns` is the documented way to get ground truth

### Secondary (MEDIUM confidence)
- [Werk #8003: New livestatus column services_with_fullstate for hosts table (checkmk.com)](https://checkmk.com/werk/8003) — corroborates `worst_service_state` as an existing hosts-table column
- [Werk #7761: New livestatus columns tags and labels (checkmk.com)](https://checkmk.com/werk/7761) — confirms `tags` column exists and its dict-shaped JSON rendering
- WebSearch snippets referencing `acknowledged`/`scheduled_downtime_depth` as documented Livestatus hosts columns (docs.checkmk.com)

### Tertiary (LOW confidence — flagged for live verification, see Assumptions Log / Open Questions)
- `parents` and `filename` column names/shapes — carried forward from training knowledge and prior project context (`ARCHITECTURE.md`'s example query), not independently re-fetched from an authoritative column list this session

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, `paho-mqtt` 2.1.0 API directly verified against installed source
- Architecture / reconciliation strategy: MEDIUM-HIGH — reasoning is sound and resolves the explicit open question, but not yet load-tested against a live broker (no podman/docker in this research sandbox)
- Livestatus column set: MEDIUM — some columns officially corroborated, others (`parents`, `filename`) carried forward as reasonable-but-unverified; flagged explicitly with a Wave 0 live-verification recommendation
- Pitfalls: HIGH — MQTT topic-injection and `./app`-doesn't-exist findings are concrete, directly observed in this repo during this research session

**Research date:** 2026-09-06
**Valid until:** 30 days (stable stack, no fast-moving dependencies) — but the Livestatus column verification (Open Question 1) should happen at implementation time regardless of research age, since it depends on the live Checkmk instance's exact version/config, not on time elapsed
