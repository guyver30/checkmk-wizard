// Payload shapes consumed by the ported dashboard logic modules (display.ts, staleness.ts,
// grouping.ts) and by the Zustand store. Every field on a payload type is optional and
// loosely typed on purpose: these shapes describe untrusted JSON crossing the MQTT trust
// boundary from scripts/mqtt_poller.py, not a contract TypeScript can enforce at runtime.
// The runtime guards in display.ts/staleness.ts/grouping.ts remain load-bearing regardless
// of what these types claim.

/**
 * The device state values scripts/mqtt_poller.py's compute_overall_state() can produce.
 * "UNREACH" can only ever appear on `host_state_raw`, never on `state` itself (Pitfall 6,
 * 11-RESEARCH.md) — see display.ts's effectiveState().
 */
export type DeviceState = "OK" | "PEND" | "WARN" | "UNKNOWN" | "CRIT" | "UNREACH" | "DOWN";

export interface DevicePayload {
  id?: string;
  alias?: string;
  state?: string;
  host_state_raw?: string;
  device_type?: string;
  folder?: string;
  timestamp?: string;
  staleness?: number | null;
  downtime?: boolean;
  acknowledged?: boolean;
  // Gauge fields produced by scripts/mqtt_poller.py::classify_host_services. A `null` value
  // means this host has no such service -- the signal the hide-on-absence rules D-03/D-06
  // key off, not a zero reading.
  cpu_percent?: number | null;
  cpu_warn?: number | null;
  cpu_crit?: number | null;
  ram_percent?: number | null;
  ram_warn?: number | null;
  ram_crit?: number | null;
  disk_percent?: number | null;
  disk_warn?: number | null;
  disk_crit?: number | null;
  disk_other_worst_percent?: number | null;
  disk_other_worst_warn?: number | null;
  disk_other_worst_crit?: number | null;
  disk_other_worst_mount?: string | null;
  smart_total?: number | null;
  smart_failing?: number | null;
}

export interface HistoryEntry {
  state?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface ServiceEntry {
  description?: string;
  state?: string;
  plugin_output?: string;
  [key: string]: unknown;
}

export interface ServiceHistoryEntry {
  timestamp?: string;
  description?: string;
  from?: string | null;
  to?: string | null;
  [key: string]: unknown;
}

export interface EventEntry {
  device_id?: string;
  state?: string;
  timestamp?: string;
  /**
   * scripts/mqtt_poller.py's `run_cycle()` publishes `from`/`to` (the state transition), not
   * `state` -- a device removal has `to: null` and a device addition has `from: null`.
   */
  from?: string | null;
  to?: string | null;
  [key: string]: unknown;
}

/**
 * One raw entry inside TopologyPayload.devices, as published by
 * scripts/mqtt_poller.py's topology_nodes() and extended by plan 13-04/PLR-13
 * (map_position/unmanaged). Every field is optional and loosely typed on purpose --
 * this describes untrusted JSON crossing the MQTT trust boundary, not a contract
 * TypeScript can enforce at runtime. topologyLayout.ts's buildMapModel() is the
 * runtime guard that actually validates/defaults these fields.
 */
export interface TopologyNode {
  id?: string;
  parents?: unknown;
  device_type?: string;
  folder?: string;
  alias?: string;
  map_position?: string | null;
  unmanaged?: boolean;
  // Phase 14, PLR-16 — populated by the poller from Checkmk host labels (plan 14-07).
  criticality?: string;
  service_criticality?: unknown;
  depends_on?: unknown;
}

/**
 * One incident published on `lan/incidents/{incident_id}/status` (retained; zero-length
 * payload is a tombstone), per plan 14-01's contract: `incident_id` is
 * `"incident-" + root host id`. Untrusted JSON crossing the MQTT trust boundary --
 * incidents.ts's normalizeIncident() is the runtime guard, not this type.
 */
export interface IncidentPayload {
  id?: string;
  root?: string;
  root_state?: string;
  inferred?: boolean;
  confirmed_down?: unknown;
  not_observable?: unknown;
  dependents?: unknown;
  worst_criticality?: string;
  since?: string | null;
  timestamp?: string;
  [key: string]: unknown;
}

export interface TopologyPayload {
  // Kept as unknown[] on purpose (untrusted JSON) -- topologyLayout.ts's buildMapModel()
  // is the runtime guard that validates/defaults each entry's TopologyNode shape.
  devices?: unknown[];
  timestamp?: string;
  [key: string]: unknown;
}

export interface PollerStatusPayload {
  status?: string;
  since?: string;
  last_poll?: string;
  device_count?: number;
  [key: string]: unknown;
}

/** D-05: "device_type" is the default grouping mode; "folder" is the alternative. */
export type GroupingMode = "type" | "folder";
