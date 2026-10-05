import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetMapDrawingStoreForTests, useMapDrawingStore } from "./mapDrawingStore";
import type { Shape } from "../lib/mapDrawing";

const line = (id: string): Shape => ({ id, type: "line", x1: 0, y1: 0, x2: 10, y2: 10, stroke: "#374151", strokeWidth: 2 });
const rect = (id: string): Shape => ({ id, type: "rect", x: 0, y: 0, w: 10, h: 10, stroke: "#374151", fill: null, strokeWidth: 2 });

function res(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}
const stored = (shapes: Shape[]) => ({ version: 1, updated_at: null, shapes });

const store = () => useMapDrawingStore.getState();

beforeEach(() => __resetMapDrawingStoreForTests());
afterEach(() => vi.unstubAllGlobals());

describe("mapDrawingStore", () => {
  it("load sets saved and draft", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, stored([line("a")]))));
    await store().load();
    expect(store().saved.shapes).toHaveLength(1);
    expect(store().draft).toHaveLength(1);
    expect(store().dirty).toBe(false);
  });

  it("load does not overwrite a dirty draft", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, stored([line("a")]))));
    store().addShape(rect("mine"));
    await store().load();
    expect(store().saved.shapes.map((s) => s.id)).toEqual(["a"]);
    expect(store().draft.map((s) => s.id)).toEqual(["mine"]);
    expect(store().dirty).toBe(true);
  });

  it("load failure sets loadError and leaves an empty drawing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(500)));
    await store().load();
    expect(store().loadError).toMatch(/500/);
    expect(store().draft).toEqual([]);
    expect(store().loading).toBe(false);
  });

  it("edits set dirty; revert restores saved and clears dirty and selection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, stored([line("a")]))));
    await store().load();
    store().addShape(rect("b"));
    store().select("b");
    expect(store().dirty).toBe(true);
    store().revert();
    expect(store().draft.map((s) => s.id)).toEqual(["a"]);
    expect(store().dirty).toBe(false);
    expect(store().selectedId).toBeNull();
  });

  it("remove, update and stroke/fill changes are edits", () => {
    store().addShape(rect("a"));
    store().select("a");
    store().setStroke("#2563eb");
    store().setFill("#16a34a");
    const r = store().draft[0] as Extract<Shape, { type: "rect" }>;
    expect([r.stroke, r.fill]).toEqual(["#2563eb", "#16a34a"]);
    store().removeShape("a");
    expect(store().draft).toEqual([]);
    expect(store().selectedId).toBeNull();
  });

  it("save success sets saved to the draft and clears dirty", async () => {
    const fetchMock = vi.fn().mockResolvedValue(res(201));
    vi.stubGlobal("fetch", fetchMock);
    store().addShape(rect("a"));
    await store().save();
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
    expect(store().saved.shapes.map((s) => s.id)).toEqual(["a"]);
    expect(store().dirty).toBe(false);
    expect(store().saveError).toBeNull();
  });

  it("save failure keeps dirty and sets saveError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(500)));
    store().addShape(rect("a"));
    await store().save();
    expect(store().dirty).toBe(true);
    expect(store().saveError).toMatch(/500/);
    expect(store().saving).toBe(false);
  });
});
