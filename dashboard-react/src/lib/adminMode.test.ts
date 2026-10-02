import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __setAdminModeForTests,
  buildAdminCommand,
  detectAdminMode,
  hostsInFolder,
  loadAdminConfig,
  newCommandId,
  parseAdminAck,
  parseAdminConfig,
  parseAdminFaked,
  previewCascade,
} from "./adminMode";
import { __setRuntimeConfigForTests, getRuntimeConfig } from "./runtimeConfig";
import type { DevicePayload } from "./types";

afterEach(() => {
  __setRuntimeConfigForTests();
  __setAdminModeForTests(false);
});

function dev(folder?: string): DevicePayload {
  return { folder } as unknown as DevicePayload;
}

describe("detectAdminMode", () => {
  it("is true only for admin=1", () => {
    expect(detectAdminMode("?admin=1")).toBe(true);
    expect(detectAdminMode("?host=a&admin=1")).toBe(true);
    expect(detectAdminMode("")).toBe(false);
    expect(detectAdminMode("?admin=0")).toBe(false);
    expect(detectAdminMode("?admin=true")).toBe(false);
    expect(detectAdminMode("?x=1")).toBe(false);
  });
});

describe("parseAdminConfig", () => {
  it("returns the credential pair", () => {
    expect(parseAdminConfig({ wsUsername: "wsadmin", wsPassword: "p" })).toEqual({
      wsUsername: "wsadmin",
      wsPassword: "p",
    });
  });
  it("returns null for missing, empty or non-string fields", () => {
    expect(parseAdminConfig({ wsUsername: "a" })).toBeNull();
    expect(parseAdminConfig({ wsUsername: "", wsPassword: "p" })).toBeNull();
    expect(parseAdminConfig({ wsUsername: "a", wsPassword: 1 })).toBeNull();
    expect(parseAdminConfig(null)).toBeNull();
  });
});

describe("loadAdminConfig", () => {
  it("applies credentials on a valid 200 response", async () => {
    const fetchFn = vi.fn(
      async () =>
        new Response(JSON.stringify({ wsUsername: "wsadmin", wsPassword: "secret" })),
    );
    expect(await loadAdminConfig(fetchFn as unknown as typeof fetch)).toBe(true);
    expect(getRuntimeConfig().wsUsername).toBe("wsadmin");
    expect(getRuntimeConfig().wsPassword).toBe("secret");
  });
  it("resolves false on 404 and keeps read-only credentials", async () => {
    const before = { ...getRuntimeConfig() };
    const fetchFn = vi.fn(async () => new Response("nope", { status: 404 }));
    expect(await loadAdminConfig(fetchFn as unknown as typeof fetch)).toBe(false);
    expect(getRuntimeConfig()).toEqual(before);
  });
  it("resolves false on non-JSON, network error and invalid body", async () => {
    const bad = vi.fn(async () => new Response("<html>"));
    expect(await loadAdminConfig(bad as unknown as typeof fetch)).toBe(false);
    const err = vi.fn(async () => {
      throw new Error("net");
    });
    expect(await loadAdminConfig(err as unknown as typeof fetch)).toBe(false);
    const invalid = vi.fn(async () => new Response(JSON.stringify({ wsUsername: "x" })));
    expect(await loadAdminConfig(invalid as unknown as typeof fetch)).toBe(false);
  });
});

describe("buildAdminCommand / newCommandId", () => {
  it("dedupes hosts preserving order", () => {
    expect(buildAdminCommand("down", ["a", "b", "a"], "id-1")).toEqual({
      id: "id-1",
      action: "down",
      hosts: ["a", "b"],
    });
  });
  it("uses an empty host list for restore_all", () => {
    expect(buildAdminCommand("restore_all", ["a"], "i").hosts).toEqual([]);
  });
  it("throws above 200 hosts", () => {
    const hosts = Array.from({ length: 201 }, (_, i) => `h${i}`);
    expect(() => buildAdminCommand("down", hosts, "i")).toThrow();
  });
  it("newCommandId is contract-shaped and unique", () => {
    const a = newCommandId();
    const b = newCommandId();
    expect(a).toMatch(/^[A-Za-z0-9-]{1,64}$/);
    expect(a).not.toBe(b);
  });
});

describe("parseAdminAck", () => {
  it("rejects malformed input", () => {
    expect(parseAdminAck(null)).toBeNull();
    expect(parseAdminAck("x")).toBeNull();
    expect(parseAdminAck({ ok: true })).toBeNull();
    expect(parseAdminAck({ id: "a", ok: "yes" })).toBeNull();
  });
  it("normalizes applied entries and drops malformed ones", () => {
    const ack = parseAdminAck({
      id: "a",
      ok: true,
      action: "down",
      detail: "d",
      applied: [
        { host: "h1", state: "DOWN", cascaded: false },
        { host: "h2", state: "BOGUS", cascaded: true },
        { state: "UP" },
        { host: "h3", state: "UP" },
      ],
      skipped: ["s", 1],
    });
    expect(ack?.applied).toEqual([
      { host: "h1", state: "DOWN", cascaded: false },
      { host: "h3", state: "UP", cascaded: false },
    ]);
    expect(ack?.skipped).toEqual(["s"]);
  });
});

describe("parseAdminFaked", () => {
  it("keeps only valid states", () => {
    expect(parseAdminFaked({ hosts: { a: "DOWN", b: "BOGUS", c: 1 } })).toEqual({ a: "DOWN" });
  });
  it("returns empty for null or shapeless payloads", () => {
    expect(parseAdminFaked(null)).toEqual({});
    expect(parseAdminFaked({})).toEqual({});
  });
});

describe("hostsInFolder", () => {
  const devices = {
    b: dev("/net"),
    a: dev("/net/sub"),
    c: dev("/network"),
    d: dev(""),
    e: dev(undefined),
  };
  it("includes subfolders but not sibling prefixes, sorted", () => {
    expect(hostsInFolder("/net", devices)).toEqual(["a", "b"]);
  });
  it("maps (no folder) to empty or missing folder", () => {
    expect(hostsInFolder("(no folder)", devices)).toEqual(["d", "e"]);
  });
});

describe("previewCascade", () => {
  const topo = [
    { id: "r1", parents: [] },
    { id: "s1", parents: ["r1"] },
    { id: "h1", parents: ["s1"] },
    { id: "um1", parents: ["r1"], unmanaged: true },
    { id: "gc1", parents: ["um1"] },
  ];
  it("cascades to descendants and stops at unmanaged", () => {
    expect(previewCascade(["r1"], topo)).toEqual(["h1", "s1", "um1"]);
  });
  it("returns nothing for a selected unmanaged root", () => {
    expect(previewCascade(["um1"], topo)).toEqual([]);
  });
  it("excludes already-selected descendants", () => {
    expect(previewCascade(["r1", "s1"], topo)).toEqual(["h1", "um1"]);
  });
  it("terminates on a parents cycle", () => {
    const cyc = [
      { id: "a", parents: ["b"] },
      { id: "b", parents: ["a"] },
    ];
    expect(previewCascade(["a"], cyc)).toEqual(["b"]);
  });
});
