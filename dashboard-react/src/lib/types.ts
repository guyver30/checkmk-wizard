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
  services?: unknown;
}

export interface HistoryEntry {
  state?: string;
  timestamp?: string;
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

export interface TopologyPayload {
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
