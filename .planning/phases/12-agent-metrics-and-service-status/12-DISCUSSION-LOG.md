# Phase 12: Agent Metrics and Service Status - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-21
**Phase:** 12-agent-metrics-and-service-status
**Areas discussed:** CPU/RAM gauge data, SMART disk-health display, Per-service status list, MQTT topic & cadence

---

## CPU/RAM gauge data

| Option | Description | Selected |
|--------|-------------|----------|
| Show gauges as N/A | Grayed-out gauge shell instead of hiding | |
| Hide gauges entirely | Only render row when device has agent data | |
| Show gauge only if service exists, else omit that one gauge | Per-gauge conditional | |

**User's choice:** Raised that SNMP-based CPU/RAM checks on network devices may exist in a
later phase — this shouldn't be baked in as "no CPU/RAM = network device" forever.

**Follow-up:**

| Option | Description | Selected |
|--------|-------------|----------|
| Show gauges as N/A | Consistent layout regardless of source | |
| Hide gauges entirely when absent | Revisit once SNMP CPU/RAM lands | ✓ |

**User's choice:** Hide gauges entirely when absent (for Phase 12's agent-based scope).

**Follow-up (granularity):**

| Option | Description | Selected |
|--------|-------------|----------|
| Per-gauge | Each gauge renders independently based on its own service | ✓ |
| All-or-nothing row | Hide whole row if any one service missing | |

**User's choice:** Per-gauge hiding (D-03).

**Follow-up (coloring):**

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror service state | Reuse existing state→color badge mapping | |
| Read warn/crit from perf_data like disk | Consistent with D-01 | ✓ |

**User's choice:** Read warn/crit from perf_data, consistent with D-01 (D-04).

**Notes:** The SNMP-for-network-devices idea is captured as a deferred idea in CONTEXT.md,
not assigned to any existing phase.

---

## SMART disk-health display

| Option | Description | Selected |
|--------|-------------|----------|
| Badge near the Disk gauge | Worst-of-all-disks badge, mirrors D-01's pattern | ✓ |
| Fold into the per-service status list | Each Smart <device> service is just a list row | |
| Both | Badge AND list rows | |

**User's choice:** Badge near the Disk gauge (D-05).

**Follow-up (fallback):**

| Option | Description | Selected |
|--------|-------------|----------|
| Hide when absent | Consistent with CPU/RAM rule | ✓ |
| Show a neutral N/A badge | Always render the slot | |

**User's choice:** Hide when absent (D-06).

**Follow-up (badge text):**

| Option | Description | Selected |
|--------|-------------|----------|
| "SMART: Fail" plus a count | e.g. "SMART: 1/2 disks failing" | ✓ |
| Just "SMART: Fail" / "SMART: Pass" | Terser, no count | |

**User's choice:** "SMART: Fail" plus a count (D-07).

---

## Per-service status list

| Option | Description | Selected |
|--------|-------------|----------|
| Everything except what's already a gauge/badge | Exclude Filesystem/CPU/Memory/Smart | |
| Everything, no exclusions | Full GET services result, duplicates gauges | |
| Only non-OK services | Zero noise but empty list on all-green hosts | |

**User's choice:** "every service selected during the wizard, except what's already in
gauge/badge" — required a confirmation round to pin down exact scope.

**Follow-up (confirmation):**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, that's it | All services minus the 4 gauge/badge ones, OK rows included | ✓ |
| Close, but only non-OK rows from that set | Filtered to WARN/CRIT/UNKNOWN | |

**User's choice:** Confirmed — all services minus gauge/badge ones, including OK rows (D-08).

**Follow-up (row content/sort):**

| Option | Description | Selected |
|--------|-------------|----------|
| Name + status badge + plugin_output, worst-first | Full "why" text, severity-sorted | ✓ |
| Name + status badge only, worst-first | Terser, matches reference image | |
| Name + status badge + plugin_output, alphabetical | Same content, stable order | |

**User's choice:** Name + status badge + plugin_output, worst-first (D-09).

**Follow-up (component):**

| Option | Description | Selected |
|--------|-------------|----------|
| kone-design-system Table | Reuses shared component | ✓ |
| Custom row list like EventHistory | Matches existing dashboard pattern | |

**User's choice:** kone-design-system Table (D-10).

---

## MQTT topic & cadence

| Option | Description | Selected |
|--------|-------------|----------|
| New retained topic: lan/devices/{id}/services | Mirrors existing per-device convention | ✓ |
| Fold into existing lan/devices/{id}/status payload | Fewer topics, bigger every-cycle payload | |

**User's choice:** New retained topic (D-11).

**Follow-up (split strategy for cadence concern):**

| Option | Description | Selected |
|--------|-------------|----------|
| Split: gauge values every cycle, service list change-only | Solves row-count concern without staling gauges | ✓ |
| One topic, everything every cycle | Simplest, but exactly the flagged ~420-row/cycle load | |
| One topic, everything change-only | Solves row-count but gauges look frozen between transitions | |

**User's choice:** Split strategy (D-12) — gauge fields fold into existing `status` payload
(every cycle); `services` topic republishes only on change.

**Follow-up (change trigger):**

| Option | Description | Selected |
|--------|-------------|----------|
| State changes only | Ignores plugin_output text drift/noise | ✓ |
| State OR plugin_output text changes | Freshest text but risks chatty republishes | |

**User's choice:** State changes only (D-13).

**Follow-up (history):**

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot only, no history | Simpler, list is a supporting detail view | |
| Add a bounded per-service history too | More complete audit trail | ✓ |

**User's choice:** Add a bounded per-service history too (D-14) — went against the
recommended simpler option, deliberate choice for a more complete audit trail.

**Follow-up (history topic shape):**

| Option | Description | Selected |
|--------|-------------|----------|
| New topic: lan/devices/{id}/service_history | Keeps device-level and service-level logs separate | ✓ |
| Fold into existing lan/devices/{id}/history | Fewer topics, shared bounded cap | |

**User's choice:** New topic `lan/devices/{id}/service_history` (D-14/D-15 combined in
CONTEXT.md as D-14).

---

## Claude's Discretion

- Exact `perf_data` field names/shape for Checkmk's "CPU utilization" and "Memory" services
  — flagged for live-verification during research, same process D-01 went through.
- SMART badge's all-pass wording (bare "SMART: Pass" vs. "SMART: Pass (2/2)").
- Bounded history length for the new `service_history` topic.
- Exact amended wording for PROJECT.md's per-service-drill-down Out of Scope entry.

## Deferred Ideas

- SNMP-sourced CPU/RAM (and potentially other) metrics for non-agent devices — raised
  during the CPU/RAM gauge discussion, not owned by any current phase. D-03's "hide on
  absence, not on device type" fallback was chosen specifically so this can land later
  without revisiting the gauge logic.
