// Which metrics are charted for history and Checkmk levels only (never forecast), the CPU
// load series spec, and where each chart's warn/crit levels come from. Pure; no store access.
//
// The service and metric names below are what scripts/mqtt_poller.py writes into
// history.metrics: GAUGE_CPU_SERVICE = "CPU utilization" (metric "util") and
// GAUGE_CPU_LOAD_SERVICE = "CPU load" (metrics "load1", "load5", "load15", from Checkmk
// 2.4.0 cmk/plugins/lib/cpu_load.py). Grep those constants if either side is renamed.

import type { DevicePayload, FitPayload } from "./types";

export const CPU_UTIL_SERVICE = "CPU utilization";
export const CPU_UTIL_METRIC = "util";
export const CPU_LOAD_SERVICE = "CPU load";

export const CPU_LOAD_SERIES = [
  { service: CPU_LOAD_SERVICE, metric: "load1", label: "1 min" },
  { service: CPU_LOAD_SERVICE, metric: "load5", label: "5 min" },
  { service: CPU_LOAD_SERVICE, metric: "load15", label: "15 min" },
] as const;

const HISTORY_ONLY_METRICS: ReadonlySet<string> = new Set([
  CPU_UTIL_METRIC,
  "load1",
  "load5",
  "load15",
]);

// Operator decision (quick 261008-kr3): CPU utilization and load swing hour to hour, so a
// straight-line projection is noise for them. They are charted for history and levels only.
export function isHistoryOnlyMetric(metric: string): boolean {
  return HISTORY_ONLY_METRICS.has(metric);
}

export interface HistoryLevels {
  warn: number | null;
  crit: number | null;
}

function finite(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

// Utilization: the device payload carries Checkmk's own levels; the fit fallback keeps what
// the chart showed before this change, which is analytics' FALLBACK_LEVELS (85, 95) when
// Checkmk has no util levels. Load: the device's absolute levels (per-core level x CPU count,
// computed by the poller), so the browser does no core scaling. Anything else: the fit's.
export function historyLevels(
  metric: string,
  device: DevicePayload | undefined,
  fit: FitPayload | null,
): HistoryLevels {
  if (metric === CPU_UTIL_METRIC) {
    return {
      warn: finite(device?.cpu_warn) ?? finite(fit?.warn),
      crit: finite(device?.cpu_crit) ?? finite(fit?.crit),
    };
  }
  if (metric === "load1" || metric === "load5" || metric === "load15") {
    return { warn: finite(device?.cpu_load_warn), crit: finite(device?.cpu_load_crit) };
  }
  return { warn: finite(fit?.warn), crit: finite(fit?.crit) };
}
