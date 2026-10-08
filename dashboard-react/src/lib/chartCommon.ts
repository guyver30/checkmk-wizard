// Chart geometry and formatting shared by ForecastChart and HistoryChart, so the two charts
// have the same frame and the same wording for values and dates.

import type { HistoryPoint } from "./historyClient";

const PLOT_H = 240;
const M = { left: 48, top: 16, right: 16, bottom: 32 } as const;
const W = 840;

export const CHART = Object.freeze({
  W,
  PLOT_H,
  M,
  H: PLOT_H + M.top + M.bottom,
  INNER_W: W - M.left - M.right,
});

export const GAP_S = 6 * 3600;
export const DAY_MS = 86400000;

export function formatValue(v: number): string {
  return String(Number(v.toFixed(2)));
}

export function formatDate(ms: number, nowMs: number): string {
  const d = new Date(ms);
  const sameYear = d.getFullYear() === new Date(nowMs).getFullYear();
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(d);
}

export function formatDateTime(ms: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(ms));
}

// Splits at gaps longer than GAP_S so a collection outage is a break, not a straight line.
export function segments(points: HistoryPoint[]): HistoryPoint[][] {
  const out: HistoryPoint[][] = [];
  let current: HistoryPoint[] = [];
  for (const p of points) {
    const prev = current[current.length - 1];
    if (prev && p.t - prev.t > GAP_S) {
      out.push(current);
      current = [];
    }
    current.push(p);
  }
  if (current.length > 0) {
    out.push(current);
  }
  return out;
}

// Sorted unique timestamps across several series (the crosshair steps through these).
export function unionTimes(series: ReadonlyArray<ReadonlyArray<{ t: number }>>): number[] {
  const seen = new Set<number>();
  for (const s of series) {
    for (const p of s) seen.add(p.t);
  }
  return [...seen].sort((a, b) => a - b);
}

export function valueAt(points: readonly HistoryPoint[], t: number): number | null {
  for (const p of points) {
    if (p.t === t) return p.v;
  }
  return null;
}
