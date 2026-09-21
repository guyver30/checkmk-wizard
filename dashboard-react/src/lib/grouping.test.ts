import { describe, expect, it } from "vitest";
import { groupKeyFor, rollUpGroup } from "./grouping";
import type { DevicePayload } from "./types";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();

describe("groupKeyFor", () => {
  it("collapses an unknown device_type to 'untyped'", () => {
    expect(groupKeyFor({ device_type: "unknown" }, "type")).toBe("untyped");
  });

  it("falls back to '(no folder)' for an empty folder", () => {
    expect(groupKeyFor({ folder: "" }, "folder")).toBe("(no folder)");
  });
});

describe("rollUpGroup", () => {
  it("returns the worst-of one OK and one CRIT device", () => {
    const devices = new Map<string, DevicePayload>([
      ["h1", { state: "OK", timestamp: FRESH_TIMESTAMP }],
      ["h2", { state: "CRIT", timestamp: FRESH_TIMESTAMP }],
    ]);
    expect(rollUpGroup(["h1", "h2"], devices, NOW_MS)).toEqual({
      worst: "CRIT",
      worstRank: 3,
      nonOkCount: 1,
      total: 2,
      hatched: false,
    });
  });

  it("excludes a stale device from worst-of but still marks the group hatched (D-15)", () => {
    const devices = new Map<string, DevicePayload>([
      ["h1", { state: "OK", timestamp: "not-a-date" }], // unparseable timestamp -> stale
      ["h2", { state: "WARN", timestamp: FRESH_TIMESTAMP }],
    ]);
    const result = rollUpGroup(["h1", "h2"], devices, NOW_MS);
    expect(result.worst).toBe("WARN");
    expect(result.hatched).toBe(true);
    expect(result.nonOkCount).toBe(1);
  });

  it("skips a device id absent from the map without incrementing total", () => {
    const devices = new Map<string, DevicePayload>([
      ["h1", { state: "OK", timestamp: FRESH_TIMESTAMP }],
    ]);
    const result = rollUpGroup(["h1", "missing"], devices, NOW_MS);
    expect(result.total).toBe(1);
  });
});
