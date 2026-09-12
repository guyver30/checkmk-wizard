# Phase 11: Live Dashboard - Pattern Map

**Mapped:** 2026-09-12
**Files analyzed:** 19 (2 modified Python, 15 new frontend, 1 modified compose, 1 modified doc)
**Analogs found:** 4 exact/role-match (Python + compose) / 15 "no analog — contract-driven" (frontend)

This phase is split into two halves with fundamentally different pattern-mapping outcomes:

1. **Python (D-17 poller extension)** — a real, in-repo analog exists for every file: the file
   being modified is its own best analog. Copy the existing conventions exactly; do not invent
   new ones.
2. **Static frontend (`dashboard/`)** — **no prior frontend exists in this repo.** Every HTML/CSS/JS
   file listed below has **no code analog**. Do not force-fit an existing Python pattern onto
   JavaScript. Instead, each frontend file's "pattern" is the relevant section of
   `11-UI-SPEC.md` (visual/behavioral contract) and `11-RESEARCH.md` (library mechanics, Code
   Examples, Patterns 1-4) — cited precisely below so the planner/executor has something as
   concrete as a code excerpt to build against.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` (D-17 additive fields) | service/utility (standalone script) | event-driven (poll cycle → MQTT publish) | **itself** — `DeviceSnapshot`, `compute_overall_state()`, `query_devices()`, `publish_device_status()` (existing code in the same file) | exact (self-extension) |
| `tests/test_mqtt_poller.py` (D-17 tests) | test | request-response (unit tests over pure functions + mocked sockets) | **itself** — existing `alias`-column tests are the direct precedent for the new `staleness`/`host_state_raw` columns | exact (self-extension) |
| `deploy/compose.yaml` (new `dashboard` service) | config | file-I/O (static bind-mount serving) | `deploy/compose.yaml`'s own `mosquitto`/`poller` service blocks (same file) | exact (self-extension) |
| `dashboard/js/config.js` | config | n/a (static constants) | `deploy/mosquitto.passwd` + `deploy/gen-mosquitto-passwd.sh`'s disposable-credential convention (concept only, not code shape — no JS analog exists) | role-match (convention only) |
| `dashboard/index.html` / `devices.html` / `details.html` | component (page shell) | request-response (static GET) + streaming (MQTT subscribe) | **none** — first HTML in this repo | no analog — see UI-SPEC Layout/Page-specific contracts |
| `dashboard/css/dashboard.css` | component (styling) | n/a | **none** | no analog — see UI-SPEC Color/Spacing/Typography |
| `dashboard/js/vendor/mqtt.min.js` | vendored dependency | n/a | **none** (not authored — downloaded verbatim per D-03) | not applicable |
| `dashboard/js/mqtt-connection.js` | service (connection lifecycle) | streaming (MQTT-over-WS) | **none in JS.** Closest *conceptual* Python analog for the "one choke point normalizes every failure" shape: `scripts/mqtt_poller.py::_publish_json()` (lines 680-696) and `_livestatus_request()` (lines 406-428) | role-match (concept only, cross-language) |
| `dashboard/js/state-store.js` | store | event-driven (wholesale-replace merge) | **none in JS.** Conceptual analog: `scripts/mqtt_poller.py::_normalise_restored_node()` defensive `.get()`/`isinstance` parsing (mentioned in RESEARCH.md's Don't-Hand-Roll table, not re-excerpted here — see that file) | role-match (concept only, cross-language) |
| `dashboard/js/staleness.js` | utility (pure functions) | transform | **none** | no analog — RESEARCH.md Code Example "Staleness detection..." is the contract |
| `dashboard/js/grouping.js` | utility (pure functions) | transform | **none** | no analog — RESEARCH.md Code Example "Worst-of group roll-up..." is the contract |
| `dashboard/js/render-shell.js` | component | request-response (DOM render) | **none** | no analog — UI-SPEC Layout section |
| `dashboard/js/render-index.js` | component | request-response (DOM render) | **none** | no analog — UI-SPEC "index.html" page contract |
| `dashboard/js/render-devices.js` | component | request-response (DOM render) | **none** | no analog — UI-SPEC "devices.html" page contract + RESEARCH.md Pattern 2 |
| `dashboard/js/render-details.js` | component | request-response (DOM render) | **none** | no analog — UI-SPEC "details.html" page contract |
| `dashboard/js/shell.js` | provider (entry point / router) | event-driven (pushState routing + MQTT dispatch) | **none** | no analog — RESEARCH.md Recommended Project Structure + Pattern 1 |
| `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (doc update) | config/doc | n/a | itself — existing §3/§6 credential-setup and service sections | exact (self-extension) |

## Pattern Assignments

### `scripts/mqtt_poller.py` (service, event-driven) — D-17 additive fields

**Analog:** itself. D-17 adds two fields (`staleness: float | None`, `host_state_raw: str`) to
the existing `DeviceSnapshot` dataclass, a `--check-columns` probe extension, and two new
payload keys in `publish_device_status()`. Every shape below is copy-exact from the current
file — do not restructure, only extend additively (mirrors the `alias` field's own D-09/D-10
precedent already in this file).

**Module docstring / "do not copy from" convention** (lines 1-35): every new module in this
project explains *why* it is shaped the way it is, and explicitly calls out what NOT to copy
from (`docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py` — both are deprecated
prototype scripts using the old paho-mqtt v1 callback API and a single-blob topic; **do not
use either as a reference for the D-17 poller change or for any dashboard JS topic naming**).

**Imports** (lines 37-53):
```python
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt
```

**Column-probe precedent to copy exactly for `staleness`** (lines 140-151, plus the dated
live-verification comment block above it at lines 77-139 — new code must add an equivalently
dated comment once `--check-columns` is run against the live site, per D-17's own
instruction):
```python
REQUIRED_HOST_COLUMNS = ("name", "state")
OPTIONAL_HOST_COLUMNS = (
    "scheduled_downtime_depth",
    "acknowledged",
    "worst_service_state",
    "parents",
    "tags",
    # Added by Phase 10 (D-10). Not covered by the 2026-09-08 column probe
    # above; live-verified present and populated on a real 2.4.0p36.cre
    # site on 2026-09-11 (plan 10-06, see the dated follow-up note above).
    "alias",
    # D-17 will append "staleness" here, following this exact comment
    # convention: cite the live --check-columns run, date, and site version.
)
```

**`DeviceSnapshot` dataclass — additive field precedent** (lines 285-304, the `alias` field is
the direct template for both new D-17 fields — same default-preserving, same docstring-comment
style):
```python
@dataclass
class DeviceSnapshot:
    """One device's current state, as derived from a single Livestatus `hosts` row."""

    id: str
    state: str
    in_downtime: bool
    acknowledged: bool
    device_type: str
    folder: str
    parents: list[str] = field(default_factory=list)
    # D-09/D-10: Checkmk's native `alias` host attribute, set by the
    # wizard's Phase 4 prompt, carried through so Phase 11 can prefer it
    # over the hostname for display. This phase only makes it available;
    # it does not decide display preference.
    alias: str = ""
    # D-17 adds here, same style:
    # staleness: float | None = None
    # host_state_raw: str = "UP"
```

**`compute_overall_state()` — the exact function D-17's `host_state_label()` sits beside**
(lines 340-344, note the collapse D-17 must NOT touch — `state` keeps meaning OK/WARN/CRIT/
UNKNOWN/DOWN; the new field is additive, not a replacement, per RESEARCH.md Pitfall 6):
```python
def compute_overall_state(host_state: int, worst_service_state: int) -> str:
    """Worst-of aggregation (D-08): host DOWN/UNREACHABLE always wins outright."""
    if host_state != 0:  # 1=DOWN, 2=UNREACHABLE (src/checkmk_wizard/livestatus.py convention)
        return "DOWN"
    return _SERVICE_STATE_NAMES.get(worst_service_state, "UNKNOWN")
```

**`select_host_columns()` — degrade-gracefully-on-absent-optional-column pattern to reuse
verbatim for `staleness`** (lines 513-536):
```python
def select_host_columns(available: set[str]) -> list[str]:
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
```

**`query_devices()` row-parsing pattern — copy the per-optional-column try/except shape
exactly for `staleness`** (lines 603-627 show the existing `acknowledged`/`parents`/`alias`
guards; D-17's `staleness` extraction and `host_state_raw` derivation from the
already-parsed `host_state` int must follow this identical defensive shape — `IndexError`/
`TypeError`/`ValueError` guarded, default on any failure, never raise mid-row):
```python
        try:
            alias = row[index["alias"]] if "alias" in index else ""
        except (IndexError, TypeError):
            alias = ""
        if not isinstance(alias, str):
            alias = ""
        # D-17 staleness follows this identical shape:
        # try:
        #     staleness = float(row[index["staleness"]]) if "staleness" in index else None
        # except (IndexError, TypeError, ValueError):
        #     staleness = None
        # host_state_raw is NOT a new column — it's derived from the
        # already-parsed `host_state` int in scope here, no new try/except
        # needed: host_state_raw = {0: "UP", 1: "DOWN", 2: "UNREACH"}.get(host_state, "UP")
```

**`publish_device_status()` — additive payload keys, exact insertion point** (lines 699-711):
```python
def publish_device_status(client: mqtt.Client, snapshot: DeviceSnapshot, timestamp: str) -> None:
    """Publish one device's current status. QoS 0: republished every cycle from live data."""
    payload = {
        "id": snapshot.id,
        "state": snapshot.state,
        "in_downtime": snapshot.in_downtime,
        "acknowledged": snapshot.acknowledged,
        "device_type": snapshot.device_type,
        "folder": snapshot.folder,
        "alias": snapshot.alias,
        # D-17 appends "staleness" and "host_state_raw" here — additive keys,
        # existing subscribers on older payload versions are unaffected.
        "timestamp": timestamp,
    }
    _publish_json(client, device_status_topic(snapshot.id), payload, qos=0, retain=True)
```

**`--check-columns` CLI diagnostic — extend, don't restructure** (lines 1191-1228): the
`for name in OPTIONAL_HOST_COLUMNS: print(...)` loop already iterates the tuple D-17 extends,
so adding `"staleness"` to `OPTIONAL_HOST_COLUMNS` is the *entire* CLI change needed — no new
argparse flag, no new branch.

**Error-handling convention to preserve:** every Livestatus network failure funnels through
`_livestatus_request()` (lines 406-428) into `LivestatusError`; every publish failure funnels
through `_publish_json()` (lines 680-696) and is swallowed with a warning log, never raised.
D-17's new code must not add a second error-handling style — extend the existing choke points,
don't bypass them.

---

### `tests/test_mqtt_poller.py` (test) — D-17 additive tests

**Analog:** itself. The `alias` column's own test set is the exact precedent shape for
`staleness`/`host_state_raw` — same test names pattern, same fixtures, same mocking style.

**Module load boilerplate — copy verbatim, do not reinvent** (lines 1-21; `scripts/` is not an
importable package, so tests load the module by file path and pre-register it in `sys.modules`
before `exec_module` because the module's own `@dataclass` + `from __future__ import
annotations` looks itself up via `sys.modules[cls.__module__]`):
```python
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_SPEC = importlib.util.spec_from_file_location(
    "mqtt_poller", Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py"
)
poller = importlib.util.module_from_spec(_SPEC)
sys.modules["mqtt_poller"] = poller
_SPEC.loader.exec_module(poller)


def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    sock.recv.side_effect = [response, b""]
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock
```

**`compute_overall_state` test shape — template for a new `host_state_label()` test**
(lines 35-48):
```python
def test_compute_overall_state_host_down_or_unreachable_wins_outright():
    assert poller.compute_overall_state(1, 0) == "DOWN"
    assert poller.compute_overall_state(2, 0) == "DOWN"

# New, following this exact naming/assertion style:
# def test_host_state_label_maps_0_1_2_to_up_down_unreach():
#     assert poller.host_state_label(0) == "UP"
#     assert poller.host_state_label(1) == "DOWN"
#     assert poller.host_state_label(2) == "UNREACH"
```

**`select_host_columns` absent-optional-column test — template for `staleness` absent**
(lines 311-313):
```python
def test_select_host_columns_omits_unavailable_optional_columns():
    result = poller.select_host_columns({"name", "state"})
    assert result == ["name", "state"]
```

**`query_devices` alias-defaulting tests — exact template for `staleness` defaulting**
(lines 416-439, three separate cases: column absent from schema, row truncated before the
column's position, non-numeric/None value — D-17's `staleness` test set should mirror all
three):
```python
def test_query_devices_alias_defaults_to_empty_string_when_column_absent():
    columns = ["name", "state", "tags"]
    sock = _fake_connection(json.dumps([["web1", 0, {}]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_alias_defaults_to_empty_string_when_row_truncated():
    columns = ["name", "state", "tags", "alias"]
    truncated_row = ["web1", 0, {}]
    sock = _fake_connection(json.dumps([truncated_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""
```

**`publish_device_status` exact-payload-keys test — template for asserting the two new
keys are present** (lines 612-641):
```python
def test_publish_device_status_uses_qos0_and_exact_payload_keys():
    mock_client = MagicMock()
    snapshot = poller.DeviceSnapshot(
        id="web1", state="OK", in_downtime=False, acknowledged=False,
        device_type="server", folder="vlan10", parents=[], alias="Web Server 1",
    )
    poller.publish_device_status(mock_client, snapshot, "2026-09-06T00:00:00+00:00")
    args, kwargs = mock_client.publish.call_args
    payload = json.loads(args[1])
    assert set(payload.keys()) == {
        "id", "state", "in_downtime", "acknowledged", "device_type",
        "folder", "alias", "timestamp",
        # D-17 test must add "staleness", "host_state_raw" to this set
        # once the fields land in DeviceSnapshot and the payload dict.
    }
```

---

### `deploy/compose.yaml` (config, file-I/O) — new `dashboard` service

**Analog:** itself — the `mosquitto` and `poller` service blocks in the same file are the
exact structural template (bind mount from repo checkout, `cmk_net` network, `restart:
unless-stopped`).

**Bind-mount + restart + network pattern to copy** (poller service, lines 130-138 and
194; mosquitto service, lines 37-57):
```yaml
  poller:
    image: python:3.12-slim
    container_name: mqtt-poller
    restart: unless-stopped
    depends_on:
      - checkmk
      - mosquitto
    working_dir: /scripts
    volumes:
      - ${POLLER_SCRIPTS_DIR:-../scripts}:/scripts:ro,z
    ...
    networks:
      - cmk_net
```

RESEARCH.md's Recommended Project Structure already drafts the exact `dashboard` service block
to add (image `nginx:alpine`, port `8090:80`, bind-mount `../dashboard:/usr/share/nginx/html:ro,z`,
`cmk_net` network) — this is the concrete shape to insert, following this file's own comment
density convention (a short comment explaining *why* the host port is 8090, matching how every
other port line in this file explains its own number, e.g. the mosquitto block's `9002` comment
at line 45).

**Env-var-configuration convention note:** this file's existing Python services configure
themselves entirely via `environment:` blocks (`LIVESTATUS_HOST`, `MQTT_HOST`, etc.) — the new
`dashboard` service has no server-side process, so per RESEARCH.md's "Established Patterns"
finding, its equivalent single-file-to-edit-per-deployment is `dashboard/js/config.js`, not an
`environment:` block. Do not add dashboard broker/Checkmk-URL settings to `compose.yaml`.

---

### Frontend files — `dashboard/**` (no in-repo analog; contract references only)

**No HTML/CSS/JS file exists anywhere in this repository today.** Do not adapt a Python
pattern's *shape* (e.g. dataclasses, `@dataclass` field defaults, `_private` helper naming) into
JavaScript — those are language conventions, not transferable idioms. What **is** transferable,
and should inform the JS style even without a code analog, are this repo's cross-cutting
values: defensive/tolerant parsing of external data, one choke-point per external I/O
operation, explicit comments citing *why* (not just *what*), and disposable-default credentials
documented plainly rather than hidden. Each transferable value is called out per file below.

| File | Contract to build against (in lieu of a code analog) | Cross-cutting value carried over from Python conventions |
|---|---|---|
| `dashboard/index.html`, `devices.html`, `details.html` | `11-UI-SPEC.md` §Layout ("Page-specific main-area contracts"), §Accessibility (no raw `innerHTML` interpolation), §Copywriting Contract (exact locked strings) | Module-level docstring-equivalent: each HTML file's `<head>` should carry an HTML comment stating its D-19/D-21 routing role, matching this repo's "every module states its purpose" convention (`site.py:1-10` style) |
| `dashboard/css/dashboard.css` | `11-UI-SPEC.md` §Spacing Scale, §Typography, §Color (exact CSS custom-property blocks are already written out in that file — copy the `:root { ... }` block verbatim, do not re-derive hex values) | — |
| `dashboard/js/vendor/mqtt.min.js` | `11-RESEARCH.md` "Installation" section — vendor exactly `mqtt@5.15.2`'s browser UMD build via the documented `curl` command; do not hand-edit the vendored file | Mirrors this repo's "pin exact versions, document the source" convention (`paho-mqtt==2.1.0` pinned in `compose.yaml`'s poller command) |
| `dashboard/js/config.js` | `11-CONTEXT.md` D-01/D-02/D-20 (hardcoded `wsreader`/`wsreader`, `location.hostname`-derived broker host, named `WS_PORT = 9002` constant, Checkmk base URL + site name) | Disposable-default-credentials-documented-plainly convention, extended from `deploy/mosquitto.passwd`/`gen-mosquitto-passwd.sh` — the file's header comment should say so explicitly, the same way this repo's other default-credential sites do (`compose.yaml` lines 22-23, 66-67, 157-159) |
| `dashboard/js/mqtt-connection.js` | `11-RESEARCH.md` Pattern 3 (hand-rolled jittered exponential backoff — the full code example is already written there; copy it near-verbatim, it is the authoritative implementation) + Pitfall 1/2/3 | One-choke-point-per-external-I/O value, same shape as `_livestatus_request()`/`_publish_json()` in `mqtt_poller.py` — every `mqtt.connect()` failure path should route through this module's reconnect handler, not be duplicated per render module |
| `dashboard/js/state-store.js` | `11-RESEARCH.md` Pattern 1 (wholesale-replace merge, full code example already written) + Don't-Hand-Roll row on JSON schema tolerance | Defensive-parse-external-data value, same shape as `_normalise_restored_node()` / `query_devices()`'s per-field try/except in `mqtt_poller.py` — a malformed retained payload should degrade (keep last-known-good), never throw and blank the page |
| `dashboard/js/staleness.js` | `11-RESEARCH.md` Code Example "Staleness detection preferring Checkmk's own value, falling back to timestamp age" (full code already written — copy near-verbatim) | — |
| `dashboard/js/grouping.js` | `11-RESEARCH.md` Code Example "Worst-of group roll-up with stale-never-masks-known-bad" (full code already written) + Pitfall 5 (maintain a `groupId -> Set<hostname>` index, not an O(n) fleet scan per update) | Mirrors `compute_overall_state()`'s own worst-of severity ordering in `mqtt_poller.py:340-344` — keep the two severity tables (Python's `_SERVICE_STATE_NAMES`/host-state collapse, JS's `SEVERITY_RANK`) conceptually in sync even though they live in different languages |
| `dashboard/js/render-shell.js` | `11-UI-SPEC.md` §Layout (shell grid CSS already written), §Connection Indicator, §Poller-offline banner (D-13/D-14, exact copy strings) | — |
| `dashboard/js/render-index.js` | `11-UI-SPEC.md` "`index.html` (D-24, DASH-01)" page contract (stats strip + card grid, exact CSS grid values given) | — |
| `dashboard/js/render-devices.js` | `11-UI-SPEC.md` "`devices.html` (DASH-02)" page contract (exact column table, default sort rule) + `11-RESEARCH.md` Pattern 2 (sortable table code example, full) | — |
| `dashboard/js/render-details.js` | `11-UI-SPEC.md` "`details.html` (DASH-03, D-19)" page contract (history-strip segment sizing, "View in Checkmk →" CTA construction) | — |
| `dashboard/js/shell.js` | `11-RESEARCH.md` Recommended Project Structure (module list + responsibilities) + Architecture Diagram's "Client-side data flow" block (topic → store-slot → re-render routing table, already fully specified) | Entry-point-composes-everything value, same shape as `wizard.py`'s `run()` composing every module — `shell.js` should only wire modules together, not contain rendering/business logic itself |

**Checkmk deep-link construction** (`details.html`'s "View in Checkmk →" CTA) has one
existing precedent worth citing even though it's Python: `src/checkmk_wizard/api.py`'s
`_site_base()`-style URL construction and `scripts/mqtt_poller.py::cmk_rest_base_url()`
(lines 431-438) both build a Checkmk base URL from host/port/site components — the JS
equivalent in `config.js`/`render-details.js` should follow the same
`{base}/{site}/check_mk/...` path-join shape rather than inventing a different one.

---

## Shared Patterns

### Defensive parsing of externally-sourced/retained data
**Source:** `scripts/mqtt_poller.py::query_devices()` (lines 603-627, per-column try/except
with a safe default) and `_normalise_restored_node()` (referenced in RESEARCH.md's Don't
Hand-Roll table)
**Apply to:** `dashboard/js/state-store.js` (every `message` handler branch), `scripts/mqtt_poller.py`'s
new `staleness`/`host_state_raw` extraction in `query_devices()`
```python
try:
    alias = row[index["alias"]] if "alias" in index else ""
except (IndexError, TypeError):
    alias = ""
if not isinstance(alias, str):
    alias = ""
```

### One choke point per external I/O operation
**Source:** `scripts/mqtt_poller.py::_livestatus_request()` (lines 406-428) and `_publish_json()`
(lines 680-696) — every network failure funnels through exactly one function and is normalized
into one exception type or one warning log, never duplicated per call site
**Apply to:** `dashboard/js/mqtt-connection.js` (the connect/reconnect wrapper is the single
place that owns `client.on('error'|'close'|'offline'|'connect', ...)`; render modules must never
attach their own listeners to the raw `mqtt.js` client)

### Disposable default credentials, documented plainly, never hidden
**Source:** `deploy/mosquitto.passwd` + `deploy/gen-mosquitto-passwd.sh` (already established in
Phase 8, D-09) and `compose.yaml`'s `cmkadmin`/`minioadmin` environment blocks
**Apply to:** `dashboard/js/config.js` — the `wsreader`/`wsreader` WS credentials (D-01) must be
accompanied by an explicit comment stating they are disposable/rotate-before-exposure defaults,
matching this project's existing convention rather than inventing a new disclosure style.

### Additive, backward-compatible schema evolution
**Source:** the `alias` field's own D-09/D-10 precedent in `DeviceSnapshot`/`publish_device_status()`
(existing default-preserving dataclass field + new dict key appended, never removed/renamed)
**Apply to:** D-17's `staleness`/`host_state_raw` fields (Python side) and the dashboard's
JSON-parsing code (JS side must tolerate a payload from an older poller version lacking these
two keys — this is explicitly required by RESEARCH.md's Don't-Hand-Roll table)

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `dashboard/index.html` | component | request-response + streaming | First HTML file in this repo — no prior page shell exists. Build against `11-UI-SPEC.md` Layout + Page-specific contracts, not a code analog. |
| `dashboard/devices.html` | component | request-response + streaming | Same as above. |
| `dashboard/details.html` | component | request-response + streaming | Same as above. |
| `dashboard/css/dashboard.css` | component (styling) | n/a | No CSS exists anywhere in this repo. `11-UI-SPEC.md`'s `:root { ... }` custom-property blocks are the literal spec to copy. |
| `dashboard/js/*.js` (all 9 modules) | service/store/utility/component/provider | streaming, event-driven, transform | No JavaScript exists anywhere in this repo. `11-RESEARCH.md`'s Pattern 1-4 code examples and Recommended Project Structure are the concrete reference; treat them as load-bearing (they were written by the phase's own research pass specifically to fill this gap), not merely illustrative. |
| `dashboard/js/vendor/mqtt.min.js` | vendored dependency | n/a | Not project code — downloaded verbatim per D-03; no "pattern" applies, only a version pin to honor (`5.15.2`, exact `curl` command given in RESEARCH.md). |
| `docs/src/mqtt_notify.py`, `docs/src/mqtt_publisher_changes.py` | (reference only — not modified this phase) | n/a | Explicitly disqualified as analogs by `scripts/mqtt_poller.py`'s own module docstring ("Do not copy from `docs/src/mqtt_publisher_changes.py`") — flagged here so the planner does not mistake their presence in `docs/src/` for a usable pattern. |

## Metadata

**Analog search scope:** `scripts/`, `tests/`, `src/checkmk_wizard/`, `deploy/`, `docs/src/`
(searched); no `dashboard/`, no `*.html`, no `*.css`, no `*.js` exist anywhere in the repo as
of this mapping (confirmed by directory listing — this is a hard fact, not an assumption).
**Files scanned:** `scripts/mqtt_poller.py` (full, 1274 lines), `tests/test_mqtt_poller.py`
(structure + 6 targeted sections, 1338 lines total), `src/checkmk_wizard/livestatus.py` (full,
56 lines), `deploy/compose.yaml` (full, 204 lines), `deploy/mosquitto.conf`/`.acl` (full),
`docs/src/mqtt_notify.py` (header, confirmed deprecated-prototype status)
**Pattern extraction date:** 2026-09-12

## Conventions

Convention derivation via the shared `gsd-tools.cjs verify conventions --derive` module was
**skipped**: neither `$CLAUDE_PLUGIN_ROOT` nor a cached `gsd-plugin` install (`~/.claude/plugins/cache/gsd-plugin/bm/*/bin/gsd-tools.cjs`) was found in this environment, so the deterministic
derivation tool could not be invoked. No `## Conventions` table (file-name casing, identifier
casing, export style, import style axes) is available this run.

In its place, the manually-observed conventions already documented in this project's own
`CLAUDE.md` remain authoritative and are the ones this PATTERNS.md file follows throughout:
`snake_case` everywhere in Python, `from __future__ import annotations` as the first line of
every module, `PascalCase` dataclasses, module-private helpers prefixed with a single
underscore, and comments that cite *why* (often with a dated live-verification note) rather than
restating *what*. The frontend half of this phase has no prior convention to derive from at all
(see "No Analog Found" above) — `11-RESEARCH.md`'s and `11-UI-SPEC.md`'s own internal
consistency (e.g. `camelCase` function names, `kebab-case` file names under `dashboard/js/`) is
the only precedent available and should simply be followed as written in those two documents.
