import { describe, expect, it } from "vitest";
import { CHART, GAP_S, formatDate, formatValue, segments, unionTimes, valueAt } from "./chartCommon";

describe("chartCommon", () => {
  it("keeps the chart geometry", () => {
    expect(CHART.W).toBe(840);
    expect(CHART.PLOT_H).toBe(240);
    expect(CHART.H).toBe(288);
    expect(CHART.INNER_W).toBe(776);
    expect(CHART.M).toEqual({ left: 48, top: 16, right: 16, bottom: 32 });
  });

  it("formats values to at most two decimals", () => {
    expect(formatValue(1.234)).toBe("1.23");
    expect(formatValue(2)).toBe("2");
  });

  it("omits the year in the same year only", () => {
    const now = Date.UTC(2026, 9, 4, 12);
    expect(formatDate(Date.UTC(2026, 8, 1, 12), now)).not.toMatch(/2026/);
    expect(formatDate(Date.UTC(2025, 8, 1, 12), now)).toMatch(/2025/);
  });

  it("splits segments at gaps longer than six hours", () => {
    const pts = [
      { t: 0, v: 1 },
      { t: 3600, v: 2 },
      { t: 3600 + GAP_S + 1, v: 3 },
    ];
    expect(segments(pts)).toEqual([[pts[0], pts[1]], [pts[2]]]);
    expect(segments([{ t: 0, v: 1 }, { t: GAP_S, v: 2 }])).toHaveLength(1);
    expect(segments([])).toEqual([]);
  });

  it("builds a sorted unique union of times and looks values up exactly", () => {
    expect(unionTimes([[{ t: 1 }, { t: 3 }], [{ t: 2 }, { t: 3 }]])).toEqual([1, 2, 3]);
    expect(valueAt([{ t: 1, v: 5 }], 1)).toBe(5);
    expect(valueAt([{ t: 1, v: 5 }], 2)).toBeNull();
  });
});
