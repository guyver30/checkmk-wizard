import { describe, expect, it } from "vitest";
import { buildTree } from "./treeModel";
import type { DevicePayload } from "./types";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();
// STALENESS_FACTOR (3) * POLL_INTERVAL_SECONDS (60) = 180s threshold (staleness.ts).
const STALE_TIMESTAMP = new Date(NOW_MS - 400 * 1000).toISOString();

describe("buildTree", () => {
  it("groups by device_type, alphabetically ordered, over two NetworkDevice and one ACS device", () => {
    const devices: Record<string, DevicePayload> = {
      nd1: { id: "nd1", device_type: "NetworkDevice", state: "OK", timestamp: FRESH_TIMESTAMP },
      nd2: { id: "nd2", device_type: "NetworkDevice", state: "OK", timestamp: FRESH_TIMESTAMP },
      acs1: { id: "acs1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree.map((g) => g.key)).toEqual(["ACS", "NetworkDevice"]);
    expect(tree.find((g) => g.key === "NetworkDevice")?.children).toHaveLength(2);
    expect(tree.find((g) => g.key === "ACS")?.children).toHaveLength(1);
  });

  it("groups by folder-derived label, with an empty/absent folder landing in '(no folder)'", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", folder: "Basement", state: "OK", timestamp: FRESH_TIMESTAMP },
      h2: { id: "h2", folder: "", state: "OK", timestamp: FRESH_TIMESTAMP },
      h3: { id: "h3", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "folder", NOW_MS);
    expect(tree.map((g) => g.key)).toEqual(["(no folder)", "Basement"]);
    expect(tree.find((g) => g.key === "(no folder)")?.children).toHaveLength(2);
  });

  it("collapses device_type 'unknown' to the single 'untyped' group and flags tagGroupMissing", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", device_type: "unknown", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree).toHaveLength(1);
    expect(tree[0].key).toBe("untyped");
    expect(tree[0].children[0].tagGroupMissing).toBe(true);
  });

  it("carries worst/worstRank/nonOkCount/total/hatched straight from rollUpGroup", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      h2: { id: "h2", device_type: "ACS", state: "CRIT", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree[0]).toMatchObject({
      worst: "CRIT",
      worstRank: 3,
      nonOkCount: 1,
      total: 2,
      hatched: false,
    });
  });

  it("each device node carries id, label, state, stale and typeIcon", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", alias: "Front Door", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree[0].children[0]).toMatchObject({
      kind: "device",
      id: "h1",
      label: "Front Door",
      state: "WARN",
      stale: false,
      typeIcon: "icon-secured",
      tagGroupMissing: false,
    });
  });

  it("reports worst: WARN and hatched: true when a group has one stale device and one WARN device", () => {
    const devices: Record<string, DevicePayload> = {
      stale1: { id: "stale1", device_type: "ACS", state: "OK", timestamp: STALE_TIMESTAMP },
      warn1: { id: "warn1", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree[0].worst).toBe("WARN");
    expect(tree[0].hatched).toBe(true);
  });

  it("orders device nodes within a group alphabetically by label", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", alias: "Zebra", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      h2: { id: "h2", alias: "Alpha", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree[0].children.map((c) => c.label)).toEqual(["Alpha", "Zebra"]);
  });

  it("returns an empty array for an empty devices map and does not throw", () => {
    expect(buildTree({}, "type", NOW_MS)).toEqual([]);
  });

  it("orders groups alphabetically by default even when a later group is worse", () => {
    const devices: Record<string, DevicePayload> = {
      a1: { id: "a1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      z1: { id: "z1", device_type: "Zebra", state: "DOWN", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS);
    expect(tree.map((g) => g.key)).toEqual(["ACS", "Zebra"]);
  });

  it("orders groups by descending worstRank when orderBySeverity is true, worst group first", () => {
    const devices: Record<string, DevicePayload> = {
      a1: { id: "a1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      z1: { id: "z1", device_type: "Zebra", state: "DOWN", timestamp: FRESH_TIMESTAMP },
    };
    // Zebra is alphabetically last but has the worse state; it must sort FIRST here and
    // LAST under the default ordering (asserted above), proving orderBySeverity actually
    // changes the order rather than being a no-op.
    const tree = buildTree(devices, "type", NOW_MS, { orderBySeverity: true });
    expect(tree.map((g) => g.key)).toEqual(["Zebra", "ACS"]);
  });

  it("breaks a worstRank tie by descending nonOkCount, then alphabetically", () => {
    const devices: Record<string, DevicePayload> = {
      a1: { id: "a1", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
      b1: { id: "b1", device_type: "Badge", state: "WARN", timestamp: FRESH_TIMESTAMP },
      b2: { id: "b2", device_type: "Badge", state: "WARN", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS, { orderBySeverity: true });
    // Both groups have worstRank 1 (WARN); Badge has nonOkCount 2 vs ACS's 1, so Badge wins
    // the tie-break despite sorting after ACS alphabetically.
    expect(tree.map((g) => g.key)).toEqual(["Badge", "ACS"]);
  });

  it("orders devices within a group by descending severity rank, then alphabetically, when orderBySeverity is true", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", alias: "Alpha", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      h2: { id: "h2", alias: "Zebra", device_type: "ACS", state: "CRIT", timestamp: FRESH_TIMESTAMP },
      h3: { id: "h3", alias: "Mid", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
    };
    const tree = buildTree(devices, "type", NOW_MS, { orderBySeverity: true });
    expect(tree[0].children.map((c) => c.label)).toEqual(["Zebra", "Mid", "Alpha"]);
  });

  it("produces a stable, deterministic order across repeated calls with identical input", () => {
    const devices: Record<string, DevicePayload> = {
      a1: { id: "a1", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
      b1: { id: "b1", device_type: "Badge", state: "WARN", timestamp: FRESH_TIMESTAMP },
      b2: { id: "b2", device_type: "Badge", state: "CRIT", timestamp: FRESH_TIMESTAMP },
    };
    const first = buildTree(devices, "type", NOW_MS, { orderBySeverity: true });
    const second = buildTree(devices, "type", NOW_MS, { orderBySeverity: true });
    expect(first).toEqual(second);
  });
});
