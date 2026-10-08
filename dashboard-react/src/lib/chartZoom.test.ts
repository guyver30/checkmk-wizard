import { describe, expect, it } from "vitest";
import {
  MIN_SPAN_MS,
  clampDomain,
  isFullDomain,
  isMinSpan,
  panBy,
  revealTime,
  zoomAt,
  type Domain,
} from "./chartZoom";

const DAY = 86400000;
const FULL: Domain = [0, 30 * DAY];

describe("clampDomain", () => {
  it("returns full for a wider domain", () => {
    expect(clampDomain([-DAY, 40 * DAY], FULL)).toEqual(FULL);
  });

  it("widens a too-narrow domain around its centre", () => {
    const d = clampDomain([10 * DAY, 10 * DAY + 1000], FULL);
    expect(d[1] - d[0]).toBeCloseTo(MIN_SPAN_MS, 3);
    expect((d[0] + d[1]) / 2).toBeCloseTo(10 * DAY + 500, 3);
  });

  it("shifts back inside on the left and right keeping the span", () => {
    expect(clampDomain([-DAY, 4 * DAY], FULL)).toEqual([0, 5 * DAY]);
    expect(clampDomain([27 * DAY, 32 * DAY], FULL)).toEqual([25 * DAY, 30 * DAY]);
  });

  it("never exceeds full when full is shorter than the minimum span", () => {
    const tiny: Domain = [1000, 1000 + 3600 * 1000];
    expect(clampDomain([1000, 2000], tiny)).toEqual(tiny);
  });

  it("does not mutate its input", () => {
    const d: Domain = [-DAY, 4 * DAY];
    clampDomain(d, FULL);
    expect(d).toEqual([-DAY, 4 * DAY]);
  });
});

describe("zoomAt", () => {
  it("halves the span keeping the anchor fraction", () => {
    const d: Domain = [10 * DAY, 14 * DAY];
    const anchor = 11 * DAY; // 25%
    const r = zoomAt(d, anchor, 0.5, FULL);
    expect(r[1] - r[0]).toBeCloseTo(2 * DAY, 3);
    expect((anchor - r[0]) / (r[1] - r[0])).toBeCloseTo(0.25, 6);
  });

  it("doubles the span", () => {
    const r = zoomAt([10 * DAY, 12 * DAY], 11 * DAY, 2, FULL);
    expect(r[1] - r[0]).toBeCloseTo(4 * DAY, 3);
  });

  it("zooming out repeatedly ends at exactly full", () => {
    let d: Domain = [10 * DAY, 11 * DAY];
    for (let i = 0; i < 12; i++) d = zoomAt(d, 10.5 * DAY, 2, FULL);
    expect(d).toEqual(FULL);
  });

  it("zooming in repeatedly stops at the minimum span", () => {
    let d: Domain = FULL;
    for (let i = 0; i < 40; i++) d = zoomAt(d, 15 * DAY, 0.5, FULL);
    expect(d[1] - d[0]).toBeCloseTo(MIN_SPAN_MS, 3);
  });

  it("clamps an anchor outside the window into it", () => {
    const d: Domain = [10 * DAY, 12 * DAY];
    const r = zoomAt(d, 50 * DAY, 0.5, FULL);
    expect(r[0]).toBeGreaterThanOrEqual(d[0]);
    expect(r[1]).toBeCloseTo(12 * DAY, 3);
  });
});

describe("panBy", () => {
  it("shifts both ends keeping the span", () => {
    const r = panBy([10 * DAY, 12 * DAY], DAY, FULL);
    expect(r).toEqual([11 * DAY, 13 * DAY]);
  });

  it("stops at either edge of full", () => {
    expect(panBy([28 * DAY, 29 * DAY], 10 * DAY, FULL)[1]).toBe(FULL[1]);
    expect(panBy([1 * DAY, 2 * DAY], -10 * DAY, FULL)[0]).toBe(FULL[0]);
  });
});

describe("revealTime", () => {
  const d: Domain = [10 * DAY, 12 * DAY];

  it("returns d unchanged when ms is inside", () => {
    expect(revealTime(d, 11 * DAY, FULL)).toEqual(d);
  });

  it("shifts so ms sits 10% inside the nearer edge", () => {
    const left = revealTime(d, 5 * DAY, FULL);
    expect(left[1] - left[0]).toBeCloseTo(2 * DAY, 3);
    expect(left[0] + 0.2 * DAY).toBeCloseTo(5 * DAY, 3);
    const right = revealTime(d, 20 * DAY, FULL);
    expect(right[1] - 0.2 * DAY).toBeCloseTo(20 * DAY, 3);
  });
});

describe("isFullDomain / isMinSpan", () => {
  it("detects full within 1 ms", () => {
    expect(isFullDomain([0.5, 30 * DAY - 0.5], FULL)).toBe(true);
    expect(isFullDomain([DAY, 30 * DAY], FULL)).toBe(false);
  });

  it("detects the minimum span", () => {
    expect(isMinSpan([DAY, DAY + MIN_SPAN_MS], FULL)).toBe(true);
    expect(isMinSpan([DAY, 2 * DAY], FULL)).toBe(false);
  });
});
