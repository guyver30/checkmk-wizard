// Gauge colour and metric-derived badge helpers for the device detail route.
//
// D-04: gauge ring colour comes from a metric's OWN warn/crit thresholds (perf_data), never
// from a Checkmk service's OK/WARN/CRIT state. stateMapping.ts (badgeForState) remains the
// single source of truth for state -> badge colour/variant/icon -- these two colour systems
// are deliberately separate and must not be merged.
//
// No DOM access, no store access, no network calls -- pure functions only.

import type { ProgressColor } from "kone-design-system";

function isFinitePositiveThreshold(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// A null/undefined/non-finite value has no reading to compare against a threshold, so it
// falls back to "success" rather than "brand" -- UI-SPEC's Color section reserves brand blue
// for focus/interactive affordances only and explicitly bars it from gauge rings.
export function gaugeColor(
  value: number | null | undefined,
  warn: number | null | undefined,
  crit: number | null | undefined,
): ProgressColor {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "success";
  }
  if (isFinitePositiveThreshold(crit) && value >= crit) {
    return "danger";
  }
  if (isFinitePositiveThreshold(warn) && value >= warn) {
    return "warning";
  }
  return "success";
}

// D-06: null/undefined/zero `total` means this host has no SMART-monitored disks -- hide the
// badge entirely (return null) rather than show a misleading "N/A".
export function smartBadge(
  total: number | null | undefined,
  failing: number | null | undefined,
): { text: string; color: ProgressColor } | null {
  if (!total) {
    return null;
  }
  const failingCount = failing ?? 0;
  if (failingCount > 0) {
    return { text: `SMART: Fail (${failingCount}/${total})`, color: "danger" };
  }
  return { text: `SMART: Pass (${total}/${total})`, color: "success" };
}

// D-01/D-03: null/undefined `percent` means every other mount point is absent -- hide the
// badge entirely rather than show 0%/N/A.
export function otherMountsLabel(percent: number | null | undefined): string | null {
  if (typeof percent !== "number" || !Number.isFinite(percent)) {
    return null;
  }
  return `Other mounts: ${Math.round(percent)}% used`;
}

// Quick 261008-d0w: the Load gauge's ring fill is load1 relative to the critical level, clamped
// to 0-100. null when there is no reading; 0 when crit is unusable (no scale to compare against).
export function loadGaugePercent(
  value: number | null | undefined,
  crit: number | null | undefined,
): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  if (typeof crit !== "number" || !Number.isFinite(crit) || crit <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (value / crit) * 100));
}

// "1/5/15 min: 0.12 / 0.30 / 0.25"; null when the 1-minute average is missing, "-" for a
// missing 5/15-minute value.
export function loadAveragesLabel(
  load1: number | null | undefined,
  load5: number | null | undefined,
  load15: number | null | undefined,
): string | null {
  if (typeof load1 !== "number" || !Number.isFinite(load1)) {
    return null;
  }
  const fmt = (v: number | null | undefined) =>
    typeof v === "number" && Number.isFinite(v) ? v.toFixed(2) : "-";
  return `1/5/15 min: ${fmt(load1)} / ${fmt(load5)} / ${fmt(load15)}`;
}
