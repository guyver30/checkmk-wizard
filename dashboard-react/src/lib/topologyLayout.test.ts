import { describe, expect, it } from "vitest";
import {
  buildMapModel,
  formatMapPosition,
  GRID_SPACING,
  initialGridPositions,
  MAP_POSITION_LABEL,
  MAP_SNAP_SPACING,
  parseMapPosition,
  snapToGrid,
  UNMANAGED_SWITCH_LABEL,
  unmanagedChildrenHint,
  unmanagedIdsFromTopology,
  withGridPositions,
} from "./topologyLayout";
import type { IncidentLookup } from "./incidents";
import type { DevicePayload } from "./types";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();

describe("label-key constants", () => {
  it("names the Checkmk host-label keys the poller and browser writer both use", () => {
    expect(MAP_POSITION_LABEL).toBe("map_position");
    expect(UNMANAGED_SWITCH_LABEL).toBe("unmanaged_switch");
    expect(GRID_SPACING).toBe(150);
  });
});

describe("parseMapPosition", () => {
  it("parses a valid positive/negative pair", () => {
    expect(parseMapPosition("120,-40")).toEqual({ x: 120, y: -40 });
  });

  it("rejects a leading space", () => {
    expect(parseMapPosition(" 1,2")).toBeNull();
  });

  it("rejects a decimal value", () => {
    expect(parseMapPosition("1.5,2")).toBeNull();
  });

  it("rejects a non-numeric string", () => {
    expect(parseMapPosition("abc")).toBeNull();
  });

  it("rejects null, undefined, and a non-string value, never throwing", () => {
    expect(parseMapPosition(null)).toBeNull();
    expect(parseMapPosition(undefined)).toBeNull();
    expect(parseMapPosition(42)).toBeNull();
  });

  it("rejects a value with more than 6 digits in one component", () => {
    expect(parseMapPosition("1234567,1")).toBeNull();
  });
});

describe("formatMapPosition", () => {
  it("rounds both coordinates to the nearest integer", () => {
    expect(formatMapPosition(119.6, -40.2)).toBe("120,-40");
  });
});

describe("snapToGrid", () => {
  it("rounds to the nearest multiple of MAP_SNAP_SPACING (= GRID_SPACING / 3 = 50)", () => {
    expect(MAP_SNAP_SPACING).toBe(GRID_SPACING / 3);
    expect(MAP_SNAP_SPACING).toBe(50);
    expect(snapToGrid(77)).toBe(100);
    expect(snapToGrid(-33)).toBe(-50);
    expect(snapToGrid(24)).toBe(0);
    expect(snapToGrid(25)).toBe(50);
    expect(snapToGrid(150)).toBe(150);
  });

  it("normalises a -0 result to +0", () => {
    expect(Object.is(snapToGrid(-10), 0)).toBe(true);
  });
});

describe("initialGridPositions", () => {
  it("lays out 5 ids in a 3-column row-major grid at 150-unit spacing", () => {
    expect(initialGridPositions(["a", "b", "c", "d", "e"])).toEqual({
      a: { x: 0, y: 0 },
      b: { x: 150, y: 0 },
      c: { x: 300, y: 0 },
      d: { x: 0, y: 150 },
      e: { x: 150, y: 150 },
    });
  });

  it("returns an empty object for an empty id list", () => {
    expect(initialGridPositions([])).toEqual({});
  });
});

describe("buildMapModel", () => {
  it("builds nodes and a parent->child edge for a simple two-host topology", () => {
    const model = buildMapModel(
      [
        { id: "sw", parents: [] },
        { id: "h1", parents: ["sw"] },
      ],
      {},
      NOW_MS,
    );
    expect(model.nodes).toHaveLength(2);
    expect(model.edges).toEqual([{ id: "sw->h1", from: "sw", to: "h1" }]);
  });

  it("produces no edge when the parent id is not in the node list", () => {
    const model = buildMapModel([{ id: "h1", parents: ["ghost"] }], {}, NOW_MS);
    expect(model.edges).toEqual([]);
  });

  it("treats a non-array parents field as empty", () => {
    const model = buildMapModel(
      [{ id: "h1", parents: "not-an-array" }],
      {},
      NOW_MS,
    );
    expect(model.edges).toEqual([]);
  });

  it("keeps only the first entry for a duplicate id", () => {
    const model = buildMapModel(
      [
        { id: "h1", alias: "first", parents: [] },
        { id: "h1", alias: "second", parents: [] },
      ],
      {},
      NOW_MS,
    );
    expect(model.nodes).toHaveLength(1);
    expect(model.nodes[0].label).toBe("first");
  });

  it("skips a non-object entry and an entry with a non-string/empty id, without throwing", () => {
    const model = buildMapModel(
      [null, 42, "bogus", { id: "" }, { id: 5 }, { id: "ok", parents: [] }],
      {},
      NOW_MS,
    );
    expect(model.nodes).toHaveLength(1);
    expect(model.nodes[0].id).toBe("ok");
  });

  it("marks a node STALE when isDeviceStale is true, otherwise uses effectiveState", () => {
    const statuses: Record<string, DevicePayload> = {
      fresh: { state: "WARN", timestamp: FRESH_TIMESTAMP },
      old: { state: "OK", timestamp: "not-a-date" },
    };
    const model = buildMapModel(
      [
        { id: "fresh", parents: [] },
        { id: "old", parents: [] },
      ],
      statuses,
      NOW_MS,
    );
    const freshNode = model.nodes.find((n) => n.id === "fresh");
    const oldNode = model.nodes.find((n) => n.id === "old");
    expect(freshNode?.state).toBe("WARN");
    expect(oldNode?.state).toBe("STALE");
  });

  it("gives a node with no status entry a state derived from isDeviceStale/effectiveState of undefined, never throwing", () => {
    const model = buildMapModel([{ id: "unknown-host", parents: [] }], {}, NOW_MS);
    expect(model.nodes[0].state).toBe("STALE");
  });

  it("uses displayName of the status payload when present, else displayName of {id, alias}", () => {
    const statuses: Record<string, DevicePayload> = {
      h1: { id: "h1", alias: "Status Alias", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const model = buildMapModel(
      [
        { id: "h1", alias: "Topology Alias", parents: [] },
        { id: "h2", alias: "Topology Only Alias", parents: [] },
      ],
      statuses,
      NOW_MS,
    );
    expect(model.nodes.find((n) => n.id === "h1")?.label).toBe("Status Alias");
    expect(model.nodes.find((n) => n.id === "h2")?.label).toBe("Topology Only Alias");
  });

  it("appends the address in parentheses to the label when the status payload has one (quick 260928-m6f)", () => {
    const statuses: Record<string, DevicePayload> = {
      router: { id: "router", state: "OK", timestamp: FRESH_TIMESTAMP, address: "192.168.0.1" },
    };
    const model = buildMapModel([{ id: "router", parents: [] }], statuses, NOW_MS);
    expect(model.nodes.find((n) => n.id === "router")?.label).toBe("router (192.168.0.1)");
  });

  it("parses map_position into node.position, or null when absent/invalid", () => {
    const model = buildMapModel(
      [
        { id: "h1", parents: [], map_position: "10,20" },
        { id: "h2", parents: [], map_position: null },
        { id: "h3", parents: [] },
      ],
      {},
      NOW_MS,
    );
    expect(model.nodes.find((n) => n.id === "h1")?.position).toEqual({ x: 10, y: 20 });
    expect(model.nodes.find((n) => n.id === "h2")?.position).toBeNull();
    expect(model.nodes.find((n) => n.id === "h3")?.position).toBeNull();
  });

  it("sets unmanaged true only when the topology entry has unmanaged === true", () => {
    const model = buildMapModel(
      [
        { id: "h1", parents: [], unmanaged: true },
        { id: "h2", parents: [], unmanaged: "yes" },
        { id: "h3", parents: [] },
      ],
      {},
      NOW_MS,
    );
    expect(model.nodes.find((n) => n.id === "h1")?.unmanaged).toBe(true);
    expect(model.nodes.find((n) => n.id === "h2")?.unmanaged).toBe(false);
    expect(model.nodes.find((n) => n.id === "h3")?.unmanaged).toBe(false);
  });

  it("never throws on a non-array topologyDevices input", () => {
    // @ts-expect-error -- deliberately passing malformed input to prove defensive parsing
    expect(() => buildMapModel("not-an-array", {}, NOW_MS)).not.toThrow();
  });

  describe("incidentLookup (DASH-15)", () => {
    it("marks a consequence node dimmed with its incident id/role, and the root as root (not dimmed)", () => {
      const lookup: IncidentLookup = new Map([
        ["h1", { incidentId: "incident-h1", role: "root", inferred: false }],
        ["h2", { incidentId: "incident-h1", role: "consequence", inferred: false }],
      ]);
      const model = buildMapModel(
        [
          { id: "h1", parents: [] },
          { id: "h2", parents: ["h1"] },
        ],
        {},
        NOW_MS,
        lookup,
      );
      const h1 = model.nodes.find((n) => n.id === "h1");
      const h2 = model.nodes.find((n) => n.id === "h2");
      expect(h1).toMatchObject({ dimmed: false, incidentId: "incident-h1", incidentRole: "root", inferredRoot: false });
      expect(h2).toMatchObject({ dimmed: true, incidentId: "incident-h1", incidentRole: "consequence" });
    });

    it("marks an inferred root's node inferredRoot true", () => {
      const lookup: IncidentLookup = new Map([
        ["h1", { incidentId: "incident-h1", role: "root", inferred: true }],
      ]);
      const model = buildMapModel([{ id: "h1", parents: [] }], {}, NOW_MS, lookup);
      expect(model.nodes.find((n) => n.id === "h1")?.inferredRoot).toBe(true);
    });

    it("without a 4th argument, every node has dimmed false / incidentId null / incidentRole null / inferredRoot false", () => {
      const model = buildMapModel(
        [
          { id: "h1", parents: [] },
          { id: "h2", parents: ["h1"] },
        ],
        {},
        NOW_MS,
      );
      for (const node of model.nodes) {
        expect(node.dimmed).toBe(false);
        expect(node.incidentId).toBeNull();
        expect(node.incidentRole).toBeNull();
        expect(node.inferredRoot).toBe(false);
      }
    });
  });
});

describe("withGridPositions", () => {
  it("keeps a saved position and offsets the rest below the largest saved y", () => {
    const nodes = [
      {
        id: "a",
        label: "A",
        deviceType: undefined,
        state: "OK",
        position: { x: 10, y: 20 },
        unmanaged: false,
        dimmed: false,
        incidentId: null,
        incidentRole: null,
        inferredRoot: false,
        hint: null,
      },
      {
        id: "b",
        label: "B",
        deviceType: undefined,
        state: "OK",
        position: null,
        unmanaged: false,
        dimmed: false,
        incidentId: null,
        incidentRole: null,
        inferredRoot: false,
        hint: null,
      },
      {
        id: "c",
        label: "C",
        deviceType: undefined,
        state: "OK",
        position: null,
        unmanaged: false,
        dimmed: false,
        incidentId: null,
        incidentRole: null,
        inferredRoot: false,
        hint: null,
      },
    ];
    const result = withGridPositions(nodes);
    const a = result.find((n) => n.id === "a");
    const b = result.find((n) => n.id === "b");
    const c = result.find((n) => n.id === "c");
    expect(a).toMatchObject({ x: 10, y: 20, saved: true });
    expect(b).toMatchObject({ x: 0, y: 170, saved: false });
    expect(c).toMatchObject({ x: 150, y: 170, saved: false });
  });

  it("starts the grid at y=0 when no node has a saved position", () => {
    const nodes = [
      {
        id: "a",
        label: "A",
        deviceType: undefined,
        state: "OK",
        position: null,
        unmanaged: false,
        dimmed: false,
        incidentId: null,
        incidentRole: null,
        inferredRoot: false,
        hint: null,
      },
    ];
    const result = withGridPositions(nodes);
    expect(result[0]).toMatchObject({ x: 0, y: 0, saved: false });
  });
});

describe("unmanaged switch display", () => {
  const dev = (id: string, state: string, extra: Partial<DevicePayload> = {}): DevicePayload =>
    ({ id, state, timestamp: FRESH_TIMESTAMP, staleness: 0, ...extra }) as DevicePayload;
  const topo = [
    { id: "sw", parents: [], unmanaged: true },
    { id: "a", parents: ["sw"] },
    { id: "b", parents: ["sw"] },
    { id: "c", parents: ["sw"] },
    { id: "d", parents: ["sw"] },
    { id: "other", parents: ["a"] },
  ];

  it("unmanagedIdsFromTopology returns only unmanaged === true ids and ignores junk", () => {
    const ids = unmanagedIdsFromTopology([
      ...topo,
      null,
      "x",
      { id: "", unmanaged: true },
      { id: "y", unmanaged: "yes" },
    ]);
    expect([...ids]).toEqual(["sw"]);
    expect(unmanagedIdsFromTopology(undefined).size).toBe(0);
  });

  it("hint counts direct children that are up", () => {
    const statuses = {
      a: dev("a", "OK"),
      b: dev("b", "OK"),
      c: dev("c", "OK"),
      d: dev("d", "DOWN", { host_state_raw: "DOWN" } as Partial<DevicePayload>),
    };
    expect(unmanagedChildrenHint("sw", topo, statuses, NOW_MS)).toBe("3 of 4 devices behind it are up");
  });

  it("hint wording for all up, one child, and none", () => {
    const two = [{ id: "sw", parents: [], unmanaged: true }, { id: "a", parents: ["sw"] }, { id: "b", parents: ["sw"] }];
    expect(unmanagedChildrenHint("sw", two, { a: dev("a", "OK"), b: dev("b", "OK") }, NOW_MS)).toBe(
      "2 of 2 devices behind it are up",
    );
    const one = [{ id: "sw", parents: [], unmanaged: true }, { id: "a", parents: ["sw"] }];
    expect(unmanagedChildrenHint("sw", one, { a: dev("a", "DOWN") }, NOW_MS)).toBe(
      "0 of 1 device behind it is up",
    );
    expect(unmanagedChildrenHint("sw", [{ id: "sw", parents: [], unmanaged: true }], {}, NOW_MS)).toBe(
      "No devices connected",
    );
  });

  it("a stale or status-less child does not count as up", () => {
    const one = [{ id: "sw", parents: [], unmanaged: true }, { id: "a", parents: ["sw"] }, { id: "b", parents: ["sw"] }];
    const statuses = { a: dev("a", "OK", { staleness: 9 }) };
    expect(unmanagedChildrenHint("sw", one, statuses, NOW_MS)).toBe("0 of 2 devices behind it are up");
  });

  it("buildMapModel maps an UNKNOWN or faked-UP unmanaged switch to UNMANAGED with a hint", () => {
    const unknown = buildMapModel(topo, { sw: dev("sw", "UNKNOWN") }, NOW_MS);
    const sw = unknown.nodes.find((n) => n.id === "sw");
    expect(sw?.state).toBe("UNMANAGED");
    expect(sw?.hint).toBe("0 of 4 devices behind it are up");
    const fakedUp = buildMapModel(topo, { sw: dev("sw", "OK", { host_state_raw: "UP" } as Partial<DevicePayload>) }, NOW_MS);
    expect(fakedUp.nodes.find((n) => n.id === "sw")?.state).toBe("UNMANAGED");
  });

  it("buildMapModel keeps DOWN and UNREACH for an unmanaged switch and null hint elsewhere", () => {
    const down = buildMapModel(topo, { sw: dev("sw", "DOWN", { host_state_raw: "DOWN" } as Partial<DevicePayload>) }, NOW_MS);
    expect(down.nodes.find((n) => n.id === "sw")?.state).toBe("DOWN");
    const unreach = buildMapModel(topo, { sw: dev("sw", "DOWN", { host_state_raw: "UNREACH" } as Partial<DevicePayload>) }, NOW_MS);
    expect(unreach.nodes.find((n) => n.id === "sw")?.state).toBe("UNREACH");
    const a = down.nodes.find((n) => n.id === "a");
    expect(a?.hint).toBeNull();
    expect(a?.state).toBe("STALE");
  });
});
