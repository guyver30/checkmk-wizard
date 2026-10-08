// Pure x-domain math for the forecast chart's zoom and pan (quick 261008-d9k). Only the
// time axis zooms; the y axis is rescaled by the chart from whatever falls in the window.
// Every function returns a fresh tuple and never mutates its input.

// Epoch milliseconds, start < end.
export type Domain = readonly [number, number];

// History is hourly averages, so 4 hours shows about 4 to 5 points: the smallest window
// that still draws a line. 1 hour would show one or two points and no line.
export const MIN_SPAN_MS = 4 * 3600 * 1000;

// The effective floor: never wider than the full domain itself.
export function minSpan(full: Domain): number {
  return Math.min(MIN_SPAN_MS, full[1] - full[0]);
}

export function clampDomain(d: Domain, full: Domain): Domain {
  const fullSpan = full[1] - full[0];
  let span = d[1] - d[0];
  if (span >= fullSpan) return [full[0], full[1]];
  const floor = minSpan(full);
  let start = d[0];
  if (span < floor) {
    const centre = (d[0] + d[1]) / 2;
    span = floor;
    start = centre - span / 2;
  }
  if (start < full[0]) start = full[0];
  if (start + span > full[1]) start = full[1] - span;
  return [start, start + span];
}

export function zoomAt(d: Domain, anchorMs: number, factor: number, full: Domain): Domain {
  const a = Math.min(Math.max(anchorMs, d[0]), d[1]);
  return clampDomain([a - (a - d[0]) * factor, a + (d[1] - a) * factor], full);
}

export function panBy(d: Domain, deltaMs: number, full: Domain): Domain {
  return clampDomain([d[0] + deltaMs, d[1] + deltaMs], full);
}

export function revealTime(d: Domain, ms: number, full: Domain): Domain {
  if (ms >= d[0] && ms <= d[1]) return [d[0], d[1]];
  const span = d[1] - d[0];
  const margin = span * 0.1;
  const start = ms < d[0] ? ms - margin : ms + margin - span;
  return clampDomain([start, start + span], full);
}

export function isFullDomain(d: Domain, full: Domain): boolean {
  return Math.abs(d[0] - full[0]) <= 1 && Math.abs(d[1] - full[1]) <= 1;
}

export function isMinSpan(d: Domain, full: Domain): boolean {
  return Math.abs(d[1] - d[0] - minSpan(full)) <= 1;
}
