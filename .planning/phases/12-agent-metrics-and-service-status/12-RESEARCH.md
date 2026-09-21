# Phase 12: Agent Metrics and Service Status - Research

**Researched:** 2026-09-21
**Domain:** Checkmk Livestatus `GET services` querying + Nagios perfdata parsing (Python poller) + React detail-panel rendering (kone-design-system)
**Confidence:** MEDIUM-HIGH (poller/Livestatus side HIGH via direct Checkmk source verification; one locked decision — D-05's SMART service name — is contradicted by that same verification and needs a live re-check before the plan locks its filter regex)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Disk & Systemd Scope (carried forward — locked before this discussion, STATE.md 2026-09-12)**

- **D-01:** Disk gauge shows `Filesystem /` as the headline (`fs_used_percent`, warn/crit
  80;90 read from perf_data), plus a badge carrying the worst `fs_used_percent` across all
  OTHER mount points on that host. Checkmk emits one `Filesystem <mount>` service per mount
  (live-verified on agent-test 2026-09-12), so the poller's services query must return every
  `Filesystem *` service, not just `/`.
- **D-02:** The per-service list (see below) and any systemd-derived data show ONLY the
  individual systemd services the operator selected during the wizard's Phase 5 "Which
  running services should be actively monitored?" prompt — never the `Systemd Service
  Summary` roll-up. The poller has no access to wizard state, but doesn't need it: Checkmk
  only creates a `Systemd Service <name>` service for wizard-chosen services, so the chosen
  set is derivable from Livestatus alone by filtering `description ~ ^Systemd Service `
  and excluding the literal `Systemd Service Summary`. Live-verified 2026-09-12 (operator
  picked cron, ModemManager, open-vm-tools; exactly those three appeared alongside Summary).

**CPU/RAM Gauges**

- **D-03:** When a device has no CPU utilization or Memory service data (SNMP-only/ping-only
  devices today), hide that specific gauge — per-gauge, not all-or-nothing for the row. A
  device missing only CPU shows RAM + Disk; Disk (per D-01) exists on nearly every Linux
  host so in practice most hosts show all three. The rule is driven by "does this service
  exist" rather than "is this a Linux host," so it degrades correctly once SNMP-based
  CPU/RAM checks exist in a future phase (raised by the user during discussion — see
  Deferred) without needing to be revisited.
- **D-04:** Gauge ring color for CPU and RAM reads warn/crit thresholds from the service's
  own `perf_data`, consistent with D-01's disk gauge — NOT the Checkmk service's own
  OK/WARN/CRIT state. (Exact `perf_data` field names/shape for Checkmk's "CPU utilization"
  and "Memory" services on this project's target Linux agent are not yet live-verified —
  flag for research, same live-verification process D-01 went through on agent-test.)

**SMART Disk-Health Display**

- **D-05:** SMART status is NOT its own 4th gauge (the DMC-server.png reference only shows
  3). It renders as a worst-of-all-disks badge next to the Disk gauge, mirroring D-01's
  "headline gauge + worst-of badge" pattern. Checkmk creates one `Smart <device>` service
  per physical disk (e.g. `/dev/sda`, `/dev/sdb`) — separate from `Filesystem *` services.
- **D-06:** The SMART badge is hidden entirely (not shown as N/A) when a host has no `Smart
  <device>` services at all — VMs with virtual disks, or hosts where smartmontools setup
  was skipped/failed during onboarding. Same hide-on-absence rule as D-03.
- **D-07:** When at least one disk is failing, the badge reads `"SMART: Fail"` plus a count,
  e.g. `"SMART: 1/2 disks failing"`. Exact wording for the all-pass case is Claude's
  discretion — resolved by 12-UI-SPEC.md: use a count in both cases, `"SMART: Pass (2/2)"` /
  `"SMART: Fail (1/2)"`.

> **RESEARCH FLAG on D-05 — see "Critical Finding" below.** Direct verification against
> Checkmk's own source (2.4.0 branch, matching this project's 2.4.0p35 baseline) shows the
> SMART check plugins register service names `"Temperature SMART %s"` and `"SMART %s
> Stats"` — **not** `"Smart <device>"`. This is a real conflict between a locked decision
> and this session's source-level verification; it is surfaced here, not silently
> overridden. See the Critical Finding and Open Questions sections.

**Per-Service Status List**

- **D-08:** The list shows every service Checkmk currently has for the host (PING, the
  wizard-chosen systemd services per D-02, and anything else the agent/wizard set up) MINUS
  the four services already surfaced as gauges/badges above (`Filesystem *`, `CPU
  utilization`, `Memory`, `Smart <device>`) — including OK rows, not filtered down to
  non-OK only. This is the full "what's being monitored" picture, not just a failure list.
- **D-09:** Each row shows service name + status badge + `plugin_output` text (e.g. "WARN -
  CPU load too high"), so the operator sees *why* without navigating further. Sorted
  worst-first: CRIT/WARN/UNKNOWN before OK.
- **D-10:** Rendered with `kone-design-system`'s existing `Table` component. **Correction
  from 12-UI-SPEC.md:** the status cell uses `StateBadgeForState` (`StateBadge.tsx`), NOT
  the design-system's own `StatusBadge` — that component's status enum
  (`connected|low-signal|entrapment|unknown`) cannot represent Checkmk's OK/WARN/CRIT/UNKNOWN.

**MQTT Topic & Publish Cadence**

- **D-11:** A new retained topic per device, `lan/devices/{id}/services`, mirrors the
  existing `lan/devices/{id}/status` / `lan/devices/{id}/history` per-device convention.
  It carries the per-service list from D-08 (the non-gauge services) — NOT the gauge values,
  per D-12's split.
- **D-12:** Gauge-backing values (CPU%, RAM%, Filesystem `fs_used_percent`, SMART worst-of
  pass/fail) are added as fields to the EXISTING `lan/devices/{id}/status` payload, which
  already republishes every poll cycle. `lan/devices/{id}/services` (the D-08 list)
  republishes only when its contents actually change.
- **D-13:** A "change" that triggers a `lan/devices/{id}/services` republish is a service's
  state (OK/WARN/CRIT/UNKNOWN) changing, or the service set itself changing (added/removed)
  — NOT `plugin_output` text drift alone. Mirrors the existing `topology_signature()`
  change-detection technique in `scripts/mqtt_poller.py`.
- **D-14:** A bounded per-service transition history IS wanted, on its own new topic,
  `lan/devices/{id}/service_history`, kept separate from `lan/devices/{id}/history` so
  neither topic's bounded cap has to share space with a very different transition rate.

**Scope Amendment (added post-UI-SPEC review, 2026-09-21)**

- **D-15:** Tree-row navigation into `DetailsRoute` is IN SCOPE. `TreeNode.tsx` device rows
  currently have no `onClick`/link; add navigation (e.g. a `Link`/`onClick` to
  `/details?id={id}`) so the feature is reachable from the fleet tree.
- **D-16:** DASH-03's bounded per-device status-history strip IS in scope. Data already
  exists (`lan/devices/{id}/history`, already subscribed and stored per-device in
  `useAppStore.ts`) — this is a rendering task (reuse `EventHistory.tsx`'s per-entry
  rendering pattern, scoped to a single device's list). DASH-03's "linking out to Checkmk's
  own UI" half is explicitly OUT of scope (D-17) — DASH-03 should NOT be marked fully
  Complete once this phase's history strip ships.
- **D-17:** The Checkmk external deep-link (the other half of DASH-03) is explicitly NOT
  built this phase. `CHECKMK_BASE_URL`/`isCheckmkLinkConfigured()` already exist in
  `lib/config.ts` for whenever it is built later.

### Claude's Discretion

- Exact `perf_data` field names for Checkmk's "CPU utilization" and "Memory" services —
  **resolved by this research** (see Standard Stack / Critical Finding below): `util` for
  CPU, `mem_used_percent` for RAM.
- SMART badge's all-pass wording — resolved by 12-UI-SPEC.md: `"SMART: Pass (2/2)"`.
- Bounded history length for the new `service_history` topic — reuse
  `DEFAULT_HISTORY_MAX_ENTRIES` (20) / an env-configurable `SERVICE_HISTORY_MAX_ENTRIES`
  mirroring the existing `HISTORY_MAX_ENTRIES` convention (see Architecture Patterns).
- Exact amended wording for PROJECT.md's "Duplicating Checkmk's own per-service drill-down
  UI" Out of Scope entry — mechanical documentation update, not a design decision.

### Deferred Ideas (OUT OF SCOPE)

- SNMP-sourced CPU/RAM (and potentially other) metrics for non-agent devices (network
  devices, ACS controllers) — not in this phase's scope. D-03's "hide on absence, not on
  device type" rule was deliberately chosen so this can land later without revisiting the
  gauge-hiding logic. No phase currently owns this.
- Time-series graphing of any metric (PROJECT.md) — permanently out of scope, no
  time-series database exists.
- Per-process CPU/RAM breakdown (DMC-server.png's "Real-time System Process" table) — no
  process-level data source exists.
- The vis-network topology map and wizard `parents` support — Phase 13, unrelated.
</user_constraints>

<phase_requirements>
## Phase Requirements

No formal REQUIREMENTS.md IDs exist yet for the gauge/service-status feature itself (ROADMAP
marks Phase 12's Requirements as "TBD — to be defined in REQUIREMENTS.md before planning").
The one existing requirement this phase touches is DASH-03, and only partially:

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-03 | `details.html` shows a per-device drill-down with a bounded status-history strip, linking out to Checkmk's own UI for full service-level detail | This phase satisfies the **history-strip half** only (D-16 — reuse `EventHistory.tsx`'s per-entry rendering against `history[id]`, data already flowing). The **"linking out to Checkmk" half is explicitly NOT built** (D-17). Per REQUIREMENTS.md's own traceability conventions (see the DASH-01 split precedent, 2026-09-12), DASH-03 should be re-worded or split so its Checkmk-link clause is tracked separately rather than marked "Complete" once this phase ships — this is a REQUIREMENTS.md bookkeeping action for the planner, not a design decision. |

**Recommendation for the planner:** before or during planning, add explicit requirement IDs
to REQUIREMENTS.md for the five capabilities this phase actually delivers and that DASH-03
does not cover: (1) CPU/RAM/Disk gauges, (2) SMART badge, (3) per-service status list, (4)
tree-row navigation (D-15), (5) the `GET services` poller extension and its two new topics.
ROADMAP.md's Phase 12 section already describes this scope in prose (its 6 numbered scope
items) but no REQ-ID exists for any of it — this phase is currently traceable only through
ROADMAP prose and CONTEXT.md decisions, not REQUIREMENTS.md's table. This is a documentation
gap, not a blocker to planning, but the plan-checker will have nothing to check plans against
in the Requirements Coverage sense unless the planner adds IDs first.
</phase_requirements>

## Summary

This phase is mostly a Python-side extension of an already-well-established poller pattern
(`scripts/mqtt_poller.py`) plus a React-side fill-in of an already-stubbed route
(`DetailsRoute.tsx`). Both sides have direct, load-bearing precedent already in the codebase:
the poller's `GET hosts` → typed dataclass → `publish_*()` pipeline generalizes cleanly to
`GET services`, and the dashboard's `kone-design-system` `ProgressCircle`/`Table`/`Badge`
primitives are already vetted and exported — no new library needs to be introduced on either
side.

The one substantive unknown flagged by CONTEXT.md's "Claude's Discretion" — the exact
`perf_data` field names for the "CPU utilization" and "Memory" services — is **resolved by
this research**, not merely narrowed: reading Checkmk's own check-plugin source (GitHub
`Checkmk/checkmk`, `2.4.0` branch, matching this project's `2.4.0p35` baseline) shows the CPU
gauge should read the perfdata metric named **`util`** and the RAM gauge should read
**`mem_used_percent`** — both with warn/crit embedded, sourced directly from the *exact*
threshold values this project's own wizard already writes via `_create_threshold_rules()`
(`checkgroup_parameters:cpu_utilization_os` → `{"util": (80.0, 90.0)}`,
`checkgroup_parameters:memory_linux` → `{"levels_ram": ("perc_used", (80.0, 90.0))}`). This
closes D-04's flagged gap with source-level confidence, not a live packet capture, but the
two are cross-consistent (the wizard's own rule shape is exactly what the check-plugin source
expects), which is about as strong as evidence gets without a live query.

The one place this research found a genuine problem, not just a gap, is D-05: the same
source-level check confirms Checkmk's SMART plugins are named `"Temperature SMART %s"` and
`"SMART %s Stats"`, not `"Smart <device>"` as D-05 states. This is flagged prominently below
rather than silently "corrected," because D-05 claims its shape was itself live-verified on
2026-09-12 — the two claims cannot both be right, and only a live Livestatus query against
the actual agent-test host (unreachable from this research sandbox) can settle which one the
live site actually reports. The planner should gate the poller's SMART service-name filter
behind a one-time live verification step, exactly like `available_host_columns()` already
does for the hosts table.

**Primary recommendation:** Extend `mqtt_poller.py` with a `GET services` query and a small,
hand-rolled Nagios-perfdata parser (the format is simple and stable; no new dependency is
justified), following the exact `available_*_columns` → `select_*_columns` →
`build_*_query` → `query_*` → `publish_*` shape the hosts pipeline already uses. On the
dashboard, fill in `DetailsRoute.tsx` using only already-installed `kone-design-system`
components (`ProgressCircle`, `Table`, `Badge` via `StateBadgeForState`) — no new npm
package is needed.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `GET services` Livestatus query, Nagios perfdata parsing | Backend (poller script) | — | Livestatus is only reachable from the poller's network position (container-boundary constraint); ROADMAP scope item 2 explicitly locks perfdata parsing to Python, not browser JS |
| Change-detection (state/set diff) for `lan/devices/{id}/services` publish cadence | Backend (poller script) | — | Same process already owns `topology_signature()`'s diff technique; keeping the diff server-side avoids shipping ~420 rows/cycle to every browser tab |
| Bounded per-service transition history (`service_history`) | Backend (poller script) | — | Same `append_bounded()` pattern as `lan/devices/{id}/history`; poller is the only writer of any retained topic |
| CPU/RAM/Disk gauges, SMART badge rendering | Browser (React) | — | Pure presentation of already-published `lan/devices/{id}/status` fields (D-12); no computation beyond percent→color mapping |
| Per-service `Table` rendering, sort-by-severity | Browser (React) | — | Pure presentation of `lan/devices/{id}/services`; sort order is a rendering concern (D-09), not a data concern |
| Tree-row → `/details?id=` navigation | Browser (React) | — | Client-side routing only (`react-router`), no data dependency |
| Status-history strip (D-16) | Browser (React) | — | Reuses already-subscribed `lan/devices/{id}/history` data; no new poller work |
| MQTT broker (topic delivery, retention) | Broker (Mosquitto) | — | Unchanged from Phase 8/9/11 — this phase adds two new topic *names* under the existing `lan/devices/{id}/*` convention, no broker config change |

## Standard Stack

### Core

No new libraries are introduced on either side of this phase. Both the poller and the
dashboard already depend on everything this phase needs.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `paho-mqtt` | >=2.1.0 (already a dependency, `pyproject.toml`) | Publish `lan/devices/{id}/services` / `lan/devices/{id}/service_history` | Already the poller's sole MQTT client; no reason to add a second |
| `kone-design-system` (`ProgressCircle`, `Table`, `Badge`) | file-linked, already installed | Gauges, service table, status badges | Confirmed present exports (`design-system/src/components/index.ts`); UI-SPEC.md explicitly forbids introducing new design-system components this phase |
| `mqtt.js` | ^5.16.0 (already a dependency, `dashboard-react/package.json`) | Subscribe to the two new topics | Already the dashboard's sole MQTT client (`mqttClient.ts`) |
| Python stdlib `re`/`str.split` | stdlib | Nagios-format `perf_data` parsing | See "Don't Hand-Roll" below — the format is simple enough that hand-rolling is the *correct* call here, not a shortcut |

**Installation:** None required — no `uv add` / `npm install` needed for this phase.

**Version verification:**
```bash
uv run python -c "import paho.mqtt.client" # already satisfied by pyproject.toml
```

### Supporting

Not applicable — no supporting libraries beyond what's already installed.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled Nagios perfdata parser (stdlib) | `nagiosplugin`, `pynagios`, `python-nagios-helpers` (PyPI) | All three are oriented at *writing* Nagios-plugin output (building perfdata to emit), not *parsing* an already-emitted perfdata string from Livestatus — none is a clean fit. Given the format's simplicity (`label=value[UOM];warn;crit;min;max`, space-separated, single-quoted only if the label contains spaces — [CITED: nagios-plugins.org/doc/guidelines.html]) and this project's demonstrated preference for owning small, stable text formats itself (LQL protocol, folder REST parsing), hand-rolling in `mqtt_poller.py` is the better fit, not a shortcut around "Don't Hand-Roll" |

## Package Legitimacy Audit

Not applicable this phase — no new external packages are being installed on either the
Python (poller) or Node (dashboard) side. `paho-mqtt`, `mqtt.js`, and `kone-design-system`
are all pre-existing dependencies from prior phases; no `uv add` / `npm install` command is
part of this phase's plan.

## Architecture Patterns

### System Architecture Diagram

```
Checkmk Livestatus (TCP :6557)
  │
  │  GET hosts  (existing)         GET services  (NEW this phase)
  │  ──────────────────            ─────────────────────────────
  ▼                                 ▼
scripts/mqtt_poller.py
  │  query_devices()                query_services()  [NEW]
  │  (unchanged)                    │
  │                                 ├─ parse_perf_data() [NEW: Nagios perfdata → dict]
  │                                 ├─ classify into: gauge-backing (CPU/RAM/Disk/SMART)
  │                                 │                 vs. per-service-list (D-08)
  │                                 │
  │  publish_device_status()        ├─ publish_device_status()  [EXTENDED: D-12 gauge fields]
  │  (existing every-cycle)         ├─ publish_services()        [NEW: change-only, D-13]
  │                                 └─ publish_service_history() [NEW: change-triggered, D-14]
  ▼                                 ▼
Mosquitto (retained topics, existing broker/ACL — no change)
  lan/devices/{id}/status   (extended payload)
  lan/devices/{id}/services         [NEW topic]
  lan/devices/{id}/service_history  [NEW topic]
  │
  │  WebSocket (existing, unchanged)
  ▼
dashboard-react/src/store/mqttClient.ts
  SUBSCRIBE_TOPICS += "lan/devices/+/services", "lan/devices/+/service_history"  [NEW]
  ▼
useAppStore.ts
  handleMessage() += two new branches (mirrors existing status/history branches)  [NEW]
  ▼
DetailsRoute.tsx  [FILLED IN this phase]
  ├─ Gauge row (CPU/RAM/Disk via ProgressCircle, reads status payload's new gauge fields)
  ├─ SMART badge (reads status payload's new smart field)
  ├─ Service Table (reads services topic, StateBadgeForState per row, sorted worst-first)
  └─ History strip (D-16, reads EXISTING history[id], no new topic)
  ▲
TreeNode.tsx  [NEW onClick this phase, D-15]
  navigates → /details?id={id}
```

### Recommended Project Structure

No new files/directories — this phase extends two existing files in place, following the
project's established "one module per concern" convention:

```
scripts/
└── mqtt_poller.py       # extended: query_services(), parse_perf_data(),
                          # publish_services(), publish_service_history(),
                          # available_service_columns(), select_service_columns(),
                          # build_services_query(); new TOPIC_*/constants

dashboard-react/src/
├── routes/
│   └── DetailsRoute.tsx        # filled in: gauge row, SMART badge, service Table, history strip
├── store/
│   ├── mqttClient.ts           # SUBSCRIBE_TOPICS += 2 new wildcard topics
│   └── useAppStore.ts          # handleMessage() += 2 new topic branches, 2 new state slices
├── components/
│   └── TreeNode.tsx            # onClick added (D-15) — no new file
└── lib/
    └── types.ts                # DevicePayload gains gauge fields; new ServiceEntry type
```

### Pattern 1: Defensive column-availability probing (extend, don't replace)

**What:** The existing `available_host_columns()` / `select_host_columns()` /
`build_hosts_query()` triad (lines ~527-573 of `mqtt_poller.py`) probes `GET columns` once at
startup, degrades gracefully on a missing optional column, and only hard-fails on a missing
*required* column.

**When to use:** Every new Livestatus query this phase adds (`GET services`) must follow the
exact same shape — a parallel `available_service_columns()` / `select_service_columns()` /
`build_services_query()` triad, probed once at startup in `run_forever()` alongside the
existing hosts-columns probe.

**Example:**
```python
# Source: scripts/mqtt_poller.py:527-573 (existing pattern to mirror)
REQUIRED_SERVICE_COLUMNS = ("host_name", "description", "state", "plugin_output")
OPTIONAL_SERVICE_COLUMNS = ("perf_data",)  # degrade to "" if the live site ever lacks it

def available_service_columns(host: str, port: int, timeout: float) -> set[str]:
    query = "GET columns\nColumns: name\nFilter: table = services\nOutputFormat: json\n\n"
    body = _livestatus_request(host, port, query, timeout)
    # ... identical parse to available_host_columns()
```

### Pattern 2: Nagios perfdata parsing (hand-rolled, in Python — never in browser JS)

**What:** Livestatus's `perf_data` column returns the raw Nagios plugin performance-data
string, e.g. `util=42.5;80.0;90.0;0;100` or `/=45.2;80.00;90.00;0;488281.25
fs_size=488281.25;;;;`. The format is `'label'=value[UOM];[warn];[crit];[min];[max]`,
space-separated, single-quoted only when the label itself contains a space
[CITED: nagios-plugins.org/doc/guidelines.html — Performance Data Format Specification].

**When to use:** Once per service row returned by `query_services()`, before classifying the
row into a gauge-backing field or a per-service-list entry (ROADMAP scope item 2 explicitly
locks this to Python).

**Example:**
```python
# New function for mqtt_poller.py — no official Checkmk/Nagios reference implementation to
# cite verbatim; format per nagios-plugins.org/doc/guidelines.html.
def parse_perf_data(raw: str) -> dict[str, dict]:
    """Parse a Nagios-format perf_data string into {label: {value, warn, crit, min, max}}.

    Defensive by design (matches this module's existing T-09-03 posture): a malformed
    token is skipped, not fatal -- one bad metric must never drop the whole service row.
    """
    result: dict[str, dict] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        label, _, rest = token.partition("=")
        label = label.strip("'")
        parts = rest.split(";")
        try:
            value = float(_strip_uom(parts[0]))
        except (ValueError, IndexError):
            continue
        def _num(i: int) -> float | None:
            try:
                return float(parts[i]) if i < len(parts) and parts[i] else None
            except ValueError:
                return None
        result[label] = {
            "value": value,
            "warn": _num(1),
            "crit": _num(2),
            "min": _num(3),
            "max": _num(4),
        }
    return result
```

### Pattern 3: `GET services` column shapes verified against Checkmk's own check-plugin source

**What:** Rather than guess field names, this research read the actual check-plugin source
for the three services this phase gauges/badges against, cross-matched against this
project's own already-deployed threshold rules (`wizard.py:1812-1824`,
`_create_threshold_rules()`).

| Service (Checkmk `service_name`) | Check plugin (GitHub path, `2.4.0` branch) | perf_data metric to read | Warn/crit source |
|---|---|---|---|
| `"CPU utilization"` | `cmk/plugins/cpu/agent_based/cpu_utilization_os.py` → `cmk/plugins/lib/cpu_util.py::check_cpu_util()` | **`util`** | `Metric("util", util, levels=levels_upper=(warn,crit), boundaries=(0,100))` — `levels` sourced from `params.get("util")`, which is exactly `checkgroup_parameters:cpu_utilization_os` → `{"util": (80.0, 90.0)}` as the wizard's own `_create_threshold_rules()` already writes. `metric_name` stays `"util"` (not `"util_average"`) because the wizard never sets an `"average"` param. [VERIFIED: github.com/Checkmk/checkmk @2.4.0 branch, `packages/cmk-plugins/cmk/plugins/lib/cpu_util.py`] |
| `"Memory"` | `cmk/plugins/memory/agent_based/mem_linux.py` → `cmk/plugins/lib/memory.py::check_element()` | **`mem_used_percent`** | `create_percent_metric=True` always yields `Metric("mem_used_percent", used*scale_to_perc, levels=(warn_pct, crit_pct), boundaries=(0.0, None))` when `levels_ram=("perc_used", (warn,crit))` is set — exactly the shape `_create_threshold_rules()` writes for `checkgroup_parameters:memory_linux`. Docstring example in the source literally shows `Metric('mem_used_percent', 23.0, levels=(12.0, 42.0), boundaries=(0.0, None))`. [VERIFIED: github.com/Checkmk/checkmk @2.4.0 branch, `packages/cmk-plugins/cmk/plugins/lib/memory.py:139-215`] |
| `"Filesystem <mount>"` | (unchanged from D-01, already live-verified 2026-09-12) | `fs_used_percent` | Already locked by D-01; no new research needed |

**Consequence for the plan:** the gauge-ring color logic (locked by 12-UI-SPEC.md's Color
section: below-warn → `success`, warn-to-crit → `warning`, ≥crit → `danger`) can be
implemented identically for all three gauges — read `perf_data[metric]["warn"/"crit"]` from
the parsed dict, never Checkmk's own service `state`. This closes D-04 with the same
confidence level D-01 already established for the disk gauge.

### Anti-Patterns to Avoid

- **Parsing `perf_data` in the browser:** ROADMAP scope item 2 and this project's own
  container-boundary philosophy both point the same direction — do it once, server-side, in
  the poller. A browser-side parser would also mean re-implementing the same format-parsing
  logic in TypeScript for no benefit.
- **Trusting `plugin_output` text for gauge coloring:** D-04 explicitly rejects this — read
  `perf_data`'s own embedded warn/crit, not the Checkmk service's aggregate OK/WARN/CRIT
  state, which can differ from a single metric's threshold crossing (e.g. a service can be
  WARN for a *different* reason than the metric the gauge cares about).
- **Filtering services by a description regex assumed rather than verified:** see the SMART
  finding below — a plausible-looking regex (`^Smart `) can be simply wrong. Every new
  service-name filter this phase adds should be probed via `--check-columns`-style
  diagnostics (or a live `GET services` dump) before being hardcoded, not assumed from a
  CONTEXT.md paraphrase.

## Critical Finding: D-05's SMART service name is contradicted by Checkmk's own source

CONTEXT.md D-05 states: *"Checkmk creates one `Smart <device>` service per physical disk
(e.g. `/dev/sda`, `/dev/sdb`)."* This research read the actual SMART check-plugin
registrations in Checkmk's GitHub repository, both at `master` and at the `2.4.0` branch
(matching this project's documented `2.4.0p35` baseline):

```
cmk/plugins/smart/agent_based/smart_ata.py:78    service_name="Temperature SMART %s"
cmk/plugins/smart/agent_based/smart_ata.py:346   service_name="SMART %s Stats"
cmk/plugins/smart/agent_based/smart_nvme.py:80   service_name="Temperature SMART %s"
cmk/plugins/smart/agent_based/smart_nvme.py:295  service_name="SMART %s Stats"
cmk/plugins/smart/agent_based/smart_scsi.py:75   service_name="Temperature SMART %s"
```
[VERIFIED: github.com/Checkmk/checkmk @2.4.0 branch, `cmk/plugins/smart/agent_based/*.py`]

There is no `"Smart %s"` (bare) template anywhere in this plugin family on either branch. The
health/failure-relevant service — the one whose `state` reflects a failing SMART attribute
(`State.CRIT` on a threshold breach, confirmed by reading `smart_ata.py`'s check function) —
is **`"SMART %s Stats"`**, not a bare `"Smart %s"`. There is also a *separate*
`"Temperature SMART %s"` service (a threshold check on drive temperature) that D-05/D-08
never mention — it is not one of the four gauge-backing exclusions D-08 lists, so under a
literal reading of D-08 it would fall into the per-service list rather than being folded into
the SMART badge.

**This is presented as a genuine conflict, not a silent correction**, because D-05 itself
claims to be a live-verified fact from a real Checkmk site on 2026-09-12 — this session
could not reach that site (no live Checkmk/Livestatus endpoint is reachable from this
research sandbox; see Environment Availability). Two explanations are both plausible:

1. D-05's "Smart <device>" was a paraphrase of the *health* service written loosely during
   discussion, and the actual live string is `"SMART /dev/sda Stats"` — consistent with this
   research.
2. The live site is running an older/patched build using a legacy SMART plugin that predates
   the 2.4-era `smart_posix`/`smart_ata`/`smart_nvme` rewrite, and truly does emit
   `"Smart <device>"`.

**Recommendation:** the planner should insert a `checkpoint:human-verify` (or a live
`--check-columns`-style probe task, mirroring how `available_host_columns()` already handles
this exact class of uncertainty) that runs `GET services` against the real agent-test host
and greps for `smart`/`SMART` service descriptions before the poller's filter regex is
hardcoded. Do not ship a filter built on either this research's finding or D-05's original
claim without that one live check — the cost of being wrong here is that the entire SMART
badge feature (D-05/D-06/D-07) silently never fires, which is exactly the kind of failure
this project's existing `available_host_columns()` probing pattern exists to prevent.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Livestatus TCP transport | A second raw-socket LQL client | `_livestatus_request()` (already exists, `mqtt_poller.py:439`) | Single choke point for every Livestatus network failure, already proven; a services-specific query is just a different query string through the same function |
| MQTT publish/retry | A second publish helper | `_publish_json()` (already exists, `mqtt_poller.py:724`) | Same reasoning — one choke point normalizes transient broker hiccups for every publish call site |
| Change detection for the services topic | A bespoke diff algorithm | `topology_signature()`'s technique (sort + tuple, compare across cycles) applied to a services-shaped signature | Already proven correct and tested for the exact "only republish when it actually changed" requirement D-13 restates |
| Bounded list truncation | A new bounded-list helper | `append_bounded()` (already exists, `mqtt_poller.py:380`) | Identical requirement (D-14) to the existing per-device history bounding — no reason for a second implementation |
| Percent-to-color-band mapping for gauges | A second color-threshold table | The single rule locked by 12-UI-SPEC.md (`success`/`warning`/`danger` from `ProgressColor`, compared against the metric's OWN warn/crit) | One rule, reused for CPU/RAM/Disk — do not let the SMART badge or per-service `StateBadgeForState` grow a second, inconsistent color rule |
| Checkmk state → badge color/variant/icon | A second mapping table in `DetailsRoute.tsx` | `badgeForState()` / `StateBadgeForState` (`lib/stateMapping.ts`, `components/StateBadge.tsx`) — already used by `TreeNode.tsx` | UI-SPEC.md's own Design System section calls this out explicitly for the per-service list |

**Key insight:** Every piece of new infrastructure this phase needs — query, parse, diff,
bound, publish, subscribe, render — already has a proven, tested analog in this exact
codebase from Phase 9-11. The work is almost entirely "add a parallel function following the
existing shape," not "design a new pattern." The one place that genuinely IS new work is the
Nagios perfdata parser itself (no prior art in this repo), which is exactly why it's called
out with its own pattern and example above rather than left implicit.

## Common Pitfalls

### Pitfall 1: Trusting a paraphrased service name without a live probe

**What goes wrong:** A filter regex built on a remembered/paraphrased Checkmk service name
(`^Smart `) silently matches zero rows if the real name is `"SMART %s Stats"` — the SMART
badge then permanently hides itself (D-06's hide-on-absence rule fires for every host, which
looks like "working as designed" rather than "broken"), and nobody notices until a real disk
failure goes unbadged.

**Why it happens:** Checkmk's own service names have changed across major versions (the
2024-era rewrite of the SMART plugin family is a real, dated example — see Critical Finding
above), and a name typed from memory during a discussion session is not the same evidence
tier as a `GET columns`/`GET services` probe against the live site.

**How to avoid:** Treat every Checkmk service-name string this phase filters on
(`Filesystem `, `CPU utilization`, `Memory`, and especially the SMART names) as
"verify-before-hardcode," the same posture `available_host_columns()` already takes for
column names. A one-line diagnostic addition to `--check-columns` (or a throwaway
`GET services\nColumns: description\nOutputFormat: json` dump during Wave 0) settles this in
seconds against a real site.

### Pitfall 2: Republishing `lan/devices/{id}/services` on `plugin_output` drift

**What goes wrong:** A chatty check (e.g. one whose output embeds a live counter, like "load
average: 1.23") changes its `plugin_output` text almost every cycle even though its `state`
never changes. If the change-detection signature (D-13) accidentally includes
`plugin_output`, the "publish only on change" cadence optimization (the whole reason D-12
split gauges from the service list) is defeated, and the ~420-row/cycle problem ROADMAP
flagged returns.

**Why it happens:** It's tempting to build the signature from "the whole service dict" for
simplicity, rather than deliberately excluding volatile text fields.

**How to avoid:** Build the services-topic signature the same way `topology_signature()`
does — an explicit tuple of *only* the fields that matter for change detection
(`host_name`, `description`, `state` — never `plugin_output`), exactly as D-13 already
specifies in prose. Write a unit test asserting that a `plugin_output`-only diff does NOT
trigger a republish, mirroring the existing `test_mqtt_poller.py` style.

### Pitfall 3: Cross-version retained-payload schema drift on `lan/devices/{id}/status`

**What goes wrong:** D-12 adds new gauge-backing keys to the *existing* `status` payload.
`mqtt_poller.py` has already been bitten by this exact class of bug once (see the dated
2026-09-11 bug-fix comment on `_normalise_restored_node()`): a retained message written by
an older poller version lacks a newer key, and a naive `dict["key"]` access on the restored
payload during `reconcile_state()` crash-loops the container under `restart:
unless-stopped`.

**Why it happens:** `reconcile_state()` only reconciles `topology`/`history`/`events` from
retained state — per-device `status` is deliberately NOT reconciled (republished fresh every
cycle from live Livestatus). This means the *specific* crash this project already fixed
cannot recur for `status` itself. However, the **new** `lan/devices/{id}/services` topic is
change-only (D-13), which means it IS a candidate for the same class of restore-time
cross-version bug if a future phase ever needs to reconcile it (it currently is not
reconciled either — `PollerState` has no `previous_services` field planned here — so this
risk is dormant, not live, in this phase's scope).

**How to avoid:** If the plan adds any reconciliation of `lan/devices/{id}/services` in a
later phase, apply the same `_normalise_restored_node()`-style defensive backfill this
codebase already uses. For *this* phase, the risk is contained because the new
`PollerState` fields (whatever tracks "previous services signature" for D-13's diff) live
only in-memory and are rebuilt fresh from live Livestatus each cold start — no retained
payload of the new shape is ever read back in by this phase's own code.

### Pitfall 4: `available_service_columns()` treating `perf_data` as required

**What goes wrong:** If `perf_data` is accidentally added to `REQUIRED_SERVICE_COLUMNS`
instead of `OPTIONAL_SERVICE_COLUMNS`, a live site that (for whatever reason — a stripped
custom Livestatus build, a future Checkmk column rename) doesn't expose it would make the
*entire* services query fail at startup, taking down gauges, SMART badge, AND the
per-service list together — a much bigger blast radius than losing gauge coloring alone.

**Why it happens:** `perf_data` feels essential because the gauges depend on it, but the
per-service list (D-08/D-09) only needs `description`/`state`/`plugin_output` — it degrades
fine without perfdata (gauges simply hide per D-03, per-service list still renders).

**How to avoid:** Mirror the existing hosts-table precedent exactly: only
`host_name`/`description`/`state` are hard requirements; `plugin_output` and `perf_data`
are optional columns that degrade to `""`/`{}` respectively, logged as a warning (matching
`select_host_columns()`'s existing `_logger.warning(...)` pattern) rather than raised as
fatal.

## Code Examples

### Extending the poller's startup column probe (mirrors existing hosts probe)

```python
# Source: pattern from scripts/mqtt_poller.py run_forever()'s existing hosts-column probe
# (lines ~1151-1179) — new code should add a parallel probe for services, not replace the
# hosts one, and should follow the same bounded-retry-then-fatal posture.
service_columns: list[str] | None = None
# ... same _STARTUP_RETRY_DELAYS_SECONDS loop shape, calling
# available_service_columns() / select_service_columns() instead of the hosts equivalents.
```

### Change-only publish for the services topic (mirrors `topology_signature()`)

```python
# Source: pattern from scripts/mqtt_poller.py topology_signature() (line 398)
def services_signature(services: list[dict]) -> tuple:
    """Order-independent signature over ONLY the fields that matter for D-13's
    'change' definition — never plugin_output (Pitfall 2 above)."""
    return tuple(
        sorted(
            (s["host_name"], s["description"], s["state"])
            for s in services
        )
    )
```

### Frontend: gauge value overlay (already locked by 12-UI-SPEC.md, shown here for the executor)

```tsx
// Source: 12-UI-SPEC.md "Typography" — Gauge value override.
// Do not modify design-system/src/components/Progress.tsx (shared library, out of scope).
<span className="relative inline-flex">
  <ProgressCircle value={cpuPercent} color={gaugeColor} size={96} strokeWidth={8} showValue={false} />
  <span className="absolute inset-0 flex items-center justify-center text-2xl font-semibold text-fg-primary">
    {cpuPercent}%
  </span>
</span>
```

### Frontend: per-service Table sort order (D-09, worst-first)

```typescript
// New helper, e.g. in a small lib/serviceSort.ts or inline in DetailsRoute.tsx —
// no existing precedent in this repo to cite; the SEVERITY_ORDER constant should live
// alongside stateMapping.ts's own STATE_SPECS table conceptually, though it does not need
// to modify that shared file.
const SEVERITY_ORDER: Record<string, number> = { CRIT: 0, WARN: 1, UNKNOWN: 2, OK: 3 };
function compareServices(a: ServiceEntry, b: ServiceEntry): number {
  const diff = (SEVERITY_ORDER[a.state] ?? 2) - (SEVERITY_ORDER[b.state] ?? 2);
  return diff !== 0 ? diff : a.description.localeCompare(b.description);
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Checkmk's legacy `smart`/`smart.temp`/`smart.stats` text-parsing plugin family (pre-2.3-era, produced services with older naming) | `smart_posix`/`smart_ata`/`smart_nvme`/`smart_scsi` agent-based v2 plugins, JSON-based (`smartctl --json`) parsing, service names `"Temperature SMART %s"` / `"SMART %s Stats"` | The `smart_posix.py` source carries a 2024 copyright header, indicating this rewrite is relatively recent within the Checkmk 2.x line | Directly relevant to D-05 — see Critical Finding. Any research or memory of "Smart <device>" naming likely predates this rewrite |
| `kernel.util`-branded CPU check (older Checkmk naming) | `cpu_utilization_os` plugin, service still displayed as `"CPU utilization"` | Ongoing refactor into `cmk/plugins/<family>/` directory layout (per Checkmk's 2.3+ plugin migration, referenced in forum discussion found during this research) | The *service name* the wizard/poller sees (`"CPU utilization"`) is stable across this refactor — only the internal plugin module path changed. Low risk for this phase. |

**Deprecated/outdated:** None directly deprecated within this phase's scope; the SMART
rewrite above is the one relevant "the world moved since your training data" case this
research surfaced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The live agent-test/target Checkmk site is running the 2.4-era SMART plugin family (`smart_posix`/`smart_ata`/etc.) that produces `"SMART %s Stats"`/`"Temperature SMART %s"`, rather than a legacy plugin that might produce `"Smart <device>"` as D-05 originally claimed | Critical Finding, D-05 | If wrong, the poller's SMART filter regex (built from whichever of the two names the plan picks) matches zero services, and the entire SMART badge feature (D-05/D-06/D-07) silently never renders on any host — recommended mitigation: a live `checkpoint:human-verify` probe before the filter is hardcoded (see Recommendation in Critical Finding) |
| A2 | `REQUIRED_SERVICE_COLUMNS` should be `(host_name, description, state)` and `OPTIONAL_SERVICE_COLUMNS` should be `(plugin_output, perf_data)`, mirroring the hosts-table required/optional split | Pattern 1, Pitfall 4 | If the live site's Livestatus `services` table lacks one of the "required" set for some unexpected reason, the whole services query becomes unavailable at startup — low risk (these are among Livestatus's oldest, most universal columns), but not literally verified against a live `GET columns` probe in this research session (no live site reachable) |
| A3 | No existing REQUIREMENTS.md requirement ID other than DASH-03 (partial) covers this phase's gauge/SMART/service-list work | Phase Requirements | If wrong (an ID exists that this research missed), the planner's requirement-coverage table would double-count or omit coverage — low risk, REQUIREMENTS.md was read in full during this research and no other candidate ID was found |

**On CPU/RAM perf_data field names (`util`, `mem_used_percent`):** these are NOT listed in
the table above despite being unverifiable via a live query in this sandbox, because they
were confirmed via direct inspection of Checkmk's own check-plugin source code on the
version-matching branch (`2.4.0`), cross-checked against this project's own already-deployed
wizard rule configuration (`_create_threshold_rules()`) which expects exactly that shape.
This is source-level verification of first-party code, not training-data recall — it is
tagged `[VERIFIED: github.com/Checkmk/checkmk @2.4.0 branch]` throughout this document, not
`[ASSUMED]`. Only D-05's SMART service name rises to the level of a genuine, flagged
disagreement, because it directly contradicts another claim (D-05 itself) that asserts its
own live verification.

## Open Questions

1. **Is the live agent-test host's SMART service actually named `"SMART <device> Stats"` (this research) or `"Smart <device>"` (D-05)?**
   - What we know: Checkmk's own GitHub source, on the version-matching `2.4.0` branch,
     unambiguously shows `"SMART %s Stats"` / `"Temperature SMART %s"` as the registered
     `service_name` templates for every SMART plugin variant (ATA/NVMe/SCSI/POSIX).
   - What's unclear: whether the live site D-05 was verified against is actually running
     that plugin generation, or an older/different one — this research sandbox has no
     reachable Livestatus endpoint to settle it directly.
   - Recommendation: a `checkpoint:human-verify` task early in the plan (Wave 0-equivalent),
     running a live `GET services` dump filtered to `description ~ (?i)smart` against the
     real agent-test host, before the poller's SMART filter regex is written into code.

2. **Should `"Temperature SMART <device>"` be excluded from the per-service list (D-08) alongside the health/stats service, or shown as a normal row?**
   - What we know: D-08 lists exactly four exclusion categories (`Filesystem *`, `CPU
     utilization`, `Memory`, `Smart <device>`) and does not mention a temperature service at
     all — because D-05's own model of "one Smart service per disk" didn't distinguish
     temperature from health/stats.
   - What's unclear: whether the temperature service was simply unknown to the discussion,
     or deliberately meant to be folded into the same exclusion as the health/stats service.
   - Recommendation: absent a stronger signal, treat `"Temperature SMART <device>"` as a
     normal per-service-list row (D-08's literal exclusion list, taken literally, doesn't
     name it) — it's informational, not a failure signal, and showing it costs nothing. Flag
     this as a discuss-phase-style micro-decision for the planner to make explicit rather
     than silently choosing one way.

3. **What are REQ IDs for this phase's actual deliverables?**
   - What we know: ROADMAP.md's Phase 12 section has 6 prose scope items and no REQ-ID
     table entries; REQUIREMENTS.md's only touchpoint is DASH-03 (partial).
   - What's unclear: whether the planner should mint new IDs (e.g. `DASH-08`..`DASH-12`) as
     part of this planning pass, or whether that's considered pre-work belonging to a
     `/bm:discuss-phase` or requirements-update step that already happened and simply wasn't
     reflected in REQUIREMENTS.md's file.
   - Recommendation: mint the IDs during planning (low-risk, mechanical), rather than
     blocking on a REQUIREMENTS.md update cycle — see Phase Requirements section above.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Live Checkmk Livestatus endpoint (agent-test host) | Live verification of `GET services` column shapes and SMART service naming (A1 above) | ✗ | — | Source-level verification against Checkmk's own GitHub repository was used instead for CPU/RAM/Filesystem field names (HIGH confidence — see Assumptions Log). SMART service naming could NOT be resolved this way with confidence — see Critical Finding; recommend a `checkpoint:human-verify` task during plan execution when a live site is reachable |
| Python 3.11+ / `uv` | Poller changes | ✓ | `uv 0.x` present on PATH, project pinned `>=3.11` | — |
| `paho-mqtt` (already a dependency) | Poller publish/subscribe | ✓ (declared in `pyproject.toml`, not import-verified in this sandbox — no project venv active) | `>=2.1.0` | — |
| Node.js / npm | Dashboard changes | ✓ | Node v24.20.0, npm 11.19.0 | — |
| `mqtt.js`, `kone-design-system`, `react-router`, `zustand` (already dependencies) | Dashboard changes | ✓ | Confirmed in `dashboard-react/package.json` (`mqtt ^5.16.0`, `react-router ^8.4.0`, `zustand ^5.0.15`) and `design-system/src/components/index.ts` (`ProgressCircle`, `Table`, `Badge` all exported) | — |
| `gh` CLI (GitHub API access) | This research session's source-level verification of Checkmk's check-plugin behavior | ✓ | 2.98.0, authenticated | Used in place of live-site verification for CPU/RAM/Filesystem perfdata shapes |

**Missing dependencies with no fallback:**
- None that block planning. The live-site gap (SMART naming) has a clear mitigation
  (a scoped `checkpoint:human-verify` task) rather than being a hard blocker.

**Missing dependencies with fallback:**
- Live Checkmk Livestatus endpoint — see above; GitHub source-level verification substituted
  for CPU/RAM/Filesystem, but NOT for the SMART naming question, which genuinely needs the
  live site.

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json` (the key is absent),
so this section is included per the default-enabled rule. This phase is read-only
visualization of already-trusted internal monitoring data (Checkmk Livestatus, reached only
from the poller's private network position) republished to a LAN-scoped, read-only-ACL'd
broker (Phase 8's existing `BRK-03` ACL, unchanged by this phase) — the threat surface is
narrow and mostly a continuation of Phase 9/11's already-accepted posture.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface — MQTT broker credentials are unchanged (`wsreader`/`wsreader` read-only, already accepted in Phase 8/11) |
| V3 Session Management | No | No sessions introduced |
| V4 Access Control | No | Broker ACL (`topic read lan/#` for WS clients) already covers the new topics by virtue of the existing `lan/#` wildcard — no new ACL rule needed, but the planner should confirm `deploy/mosquitto.acl`'s pattern still matches `lan/devices/+/services` and `lan/devices/+/service_history` (it should, since both are still under `lan/devices/`) |
| V5 Input Validation | Yes | Two new untrusted-input boundaries: (1) the poller parsing Livestatus's `perf_data`/`plugin_output` strings — apply the same defensive, never-raise posture as `query_devices()`'s existing per-column `try/except` (see Pitfall 4, Pattern 2's `parse_perf_data()`); (2) the dashboard parsing the two new retained JSON topics — extend `useAppStore.ts`'s existing `parsePayload()`/`isPlainObject()` guards to the new topics, exactly as the existing `status`/`history`/`topology` branches already do. No hand-rolled sanitization library needed — this project's existing "parse defensively, drop on malformed, never throw" convention already covers this class of risk |
| V6 Cryptography | No | No new secrets, tokens, or crypto material introduced |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Malformed/oversized `perf_data` or `plugin_output` string from a compromised or buggy check plugin crashing the poller | Denial of Service | Defensive parsing (try/except per field, skip-not-raise per malformed token) — matches this module's existing T-09-03 convention throughout `query_devices()` |
| A crafted service `description` containing MQTT-unsafe characters propagating into a topic name | Tampering (topic injection) | Not applicable here — service descriptions are payload content (inside the JSON body of `lan/devices/{id}/services`), never interpolated into a topic string themselves; only the already-validated `device_id` (via `is_publishable_device_id()`) forms part of any topic path. No new topic-injection surface is introduced |
| Rendering untrusted `plugin_output` text in the service `Table` | Tampering / Information Disclosure (stored XSS) | React's default JSX text-content escaping already neutralizes this — the plan must not introduce `dangerouslySetInnerHTML` for the `Output` column (12-UI-SPEC.md's spec renders it as plain wrapped text, consistent with this) |
| A malformed retained JSON payload on either new topic corrupting `useAppStore`'s state | Tampering / Denial of Service | `useAppStore.ts`'s existing `parsePayload()` + `isPlainObject()`/`Array.isArray()` guards, extended verbatim to the two new topics — last-known-good is kept on any parse failure, matching every existing branch in `handleMessage()` |

## Sources

### Primary (HIGH confidence)

- `github.com/Checkmk/checkmk` (`2.4.0` branch, version-matched to this project's documented
  `2.4.0p35` CE baseline), fetched via authenticated `gh api` calls in this session:
  - `packages/cmk-plugins/cmk/plugins/lib/cpu_util.py` — `check_cpu_util()`, confirms
    `Metric("util", ...)` with warn/crit from `params["util"]`
  - `cmk/plugins/cpu/agent_based/cpu_utilization_os.py` — confirms `service_name="CPU
    utilization"`
  - `packages/cmk-plugins/cmk/plugins/lib/memory.py` — `check_element()`, confirms
    `Metric("mem_used_percent", ...)` when `create_percent_metric=True`
  - `cmk/plugins/memory/agent_based/mem_linux.py` — confirms `checkgroup_parameters:
    memory_linux` → `levels_ram` → `check_element(..., metric_name="mem_used", 
    create_percent_metric=True)`
  - `cmk/plugins/smart/agent_based/smart_ata.py`, `smart_nvme.py`, `smart_scsi.py` — confirm
    `service_name="Temperature SMART %s"` / `service_name="SMART %s Stats"`, contradicting
    D-05
- `src/checkmk_wizard/wizard.py:1764-1831` (`_create_threshold_rules()`) — this project's own
  already-deployed Checkmk rule configuration, cross-verified against the plugin source above
- `scripts/mqtt_poller.py` (full file read) — the existing pipeline this phase extends
- `dashboard-react/src/routes/DetailsRoute.tsx`, `store/mqttClient.ts`, `store/useAppStore.ts`,
  `lib/stateMapping.ts`, `components/StateBadge.tsx`, `components/TreeNode.tsx`,
  `components/EventHistory.tsx`, `components/EventRow.tsx`, `lib/types.ts`, `lib/config.ts`,
  `lib/display.ts`, `lib/staleness.ts`, `App.tsx` — full reads of every file this phase touches
- `design-system/src/components/Progress.tsx`, `Table.tsx`, `Badge.tsx`, `index.ts` — full
  reads confirming exact prop shapes and exports
- `.planning/phases/12-agent-metrics-and-service-status/12-CONTEXT.md`,
  `12-UI-SPEC.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`,
  `.planning/config.json`

### Secondary (MEDIUM confidence)

- `nagios-plugins.org/doc/guidelines.html` (via WebFetch) — Performance Data Format
  Specification, used to confirm the general Nagios perfdata syntax this project's own D-01
  already empirically matches

### Tertiary (LOW confidence)

- WebSearch results on Checkmk CPU/Memory perfdata field names (forum posts, integration
  pages) — superseded by the primary GitHub source-code verification above; kept here only
  as corroborating context, not relied upon for any claim in this document

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; every reused piece already has a proven call site
  in this exact codebase
- Architecture: HIGH — the poller/dashboard pipeline shape is a direct, mechanical extension
  of an already-shipped, already-tested pattern (Phase 9/11)
- Perfdata field names (CPU `util`, RAM `mem_used_percent`): HIGH — verified against
  version-matched Checkmk source, cross-consistent with this project's own deployed rule
  config
- SMART service naming (D-05): LOW/CONTRADICTED — source-level research directly conflicts
  with a locked decision that itself claims live verification; needs a live re-check, see
  Critical Finding and Open Question 1
- Pitfalls: HIGH — three of four pitfalls are near-direct restatements of already-encountered,
  already-fixed bugs in this exact codebase (dated comments in `mqtt_poller.py`); the fourth
  (Pitfall 1, the SMART naming trap) is this session's own finding

**Research date:** 2026-09-21
**Valid until:** 30 days for the poller/dashboard architecture guidance (stable, first-party
code); the SMART service-naming finding should be treated as valid only until the
recommended live verification happens — do not let it age into an assumed fact either way
