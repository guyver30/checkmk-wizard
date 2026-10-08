import { describe, expect, it } from "vitest";
import { CPU_LOAD_SERIES, historyLevels, isHistoryOnlyMetric } from "./historyCharts";
import type { DevicePayload, FitPayload } from "./types";

const dev = (o: Partial<DevicePayload>) => o as DevicePayload;
const fit = (warn: number | null, crit: number | null) => ({ warn, crit }) as FitPayload;

describe("isHistoryOnlyMetric", () => {
  it("is true for util and the load averages only", () => {
    for (const m of ["util", "load1", "load5", "load15"]) expect(isHistoryOnlyMetric(m)).toBe(true);
    for (const m of ["fs_used_percent", "mem_used_percent", ""]) expect(isHistoryOnlyMetric(m)).toBe(false);
  });
});

describe("CPU_LOAD_SERIES", () => {
  it("lists load1, load5 and load15 of the CPU load service", () => {
    expect(CPU_LOAD_SERIES.map((s) => [s.service, s.metric, s.label])).toEqual([
      ["CPU load", "load1", "1 min"],
      ["CPU load", "load5", "5 min"],
      ["CPU load", "load15", "15 min"],
    ]);
  });
});

describe("historyLevels", () => {
  it("prefers the device's Checkmk levels for util", () => {
    expect(historyLevels("util", dev({ cpu_warn: 80, cpu_crit: 90 }), fit(85, 95))).toEqual({ warn: 80, crit: 90 });
  });
  it("falls back to the fit per level, then to null", () => {
    expect(historyLevels("util", dev({ cpu_warn: null, cpu_crit: null }), fit(85, 95))).toEqual({ warn: 85, crit: 95 });
    expect(historyLevels("util", dev({ cpu_warn: 80, cpu_crit: null }), fit(85, 95))).toEqual({ warn: 80, crit: 95 });
    expect(historyLevels("util", undefined, null)).toEqual({ warn: null, crit: null });
    expect(historyLevels("util", dev({ cpu_warn: NaN, cpu_crit: Infinity }), null)).toEqual({ warn: null, crit: null });
  });
  it("uses the absolute load levels for load averages", () => {
    for (const m of ["load1", "load5", "load15"]) {
      expect(historyLevels(m, dev({ cpu_load_warn: 12, cpu_load_crit: 20 }), fit(1, 2))).toEqual({ warn: 12, crit: 20 });
    }
    expect(historyLevels("load1", dev({}), null)).toEqual({ warn: null, crit: null });
  });
  it("uses the fit's levels for other metrics", () => {
    expect(historyLevels("fs_used_percent", undefined, fit(80, 90))).toEqual({ warn: 80, crit: 90 });
  });
});
