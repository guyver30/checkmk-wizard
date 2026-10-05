import { afterEach, describe, expect, it, vi } from "vitest";
import { MAP_DRAWING_URL, MapDrawingError, loadDrawing, saveDrawing } from "./mapDrawingClient";
import { MAX_DRAWING_BYTES, MAX_TEXT_LENGTH, emptyDrawing, type Shape } from "./mapDrawing";

function res(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : typeof body === "string" ? body : JSON.stringify(body), { status });
}

afterEach(() => vi.unstubAllGlobals());

describe("loadDrawing", () => {
  it("returns the sanitised drawing on 200", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      res(200, { version: 1, updated_at: "t", shapes: [
        { id: "a", type: "line", x1: 0, y1: 0, x2: 1, y2: 1 },
        { id: "b", type: "star" },
      ] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const d = await loadDrawing();
    expect(d.shapes.map((s) => s.id)).toEqual(["a"]);
    expect(fetchMock).toHaveBeenCalledWith(MAP_DRAWING_URL, expect.objectContaining({ cache: "no-store" }));
  });

  it("treats 404 as an empty drawing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(404)));
    expect(await loadDrawing()).toEqual(emptyDrawing());
  });

  it("rejects on 500, network error and non-JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(500)));
    await expect(loadDrawing()).rejects.toBeInstanceOf(MapDrawingError);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    await expect(loadDrawing()).rejects.toBeInstanceOf(MapDrawingError);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, "<html>spa</html>")));
    await expect(loadDrawing()).rejects.toBeInstanceOf(MapDrawingError);
  });
});

describe("saveDrawing", () => {
  const shapes: Shape[] = [{ id: "a", type: "line", x1: 0, y1: 0, x2: 1, y2: 1, stroke: "#374151", strokeWidth: 2 }];

  it("PUTs the serialised drawing as application/json", async () => {
    const fetchMock = vi.fn().mockResolvedValue(res(201));
    vi.stubGlobal("fetch", fetchMock);
    const saved = await saveDrawing(shapes);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/map-drawing.json");
    expect(init.method).toBe("PUT");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body).shapes).toHaveLength(1);
    expect(saved.shapes).toEqual(shapes);
    expect(saved.updated_at).toEqual(expect.any(String));
  });

  it.each([[413, /too large/i], [415, /content type/i], [500, /500/]])("rejects on %i", async (status, msg) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(status)));
    await expect(saveDrawing(shapes)).rejects.toThrow(msg);
  });

  it("rejects a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    await expect(saveDrawing(shapes)).rejects.toBeInstanceOf(MapDrawingError);
  });

  it("rejects an oversize drawing before calling fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const big: Shape[] = Array.from({ length: 500 }, (_, i) => ({
      id: `${i}`.padEnd(400, "x"), type: "text", x: 0, y: 0,
      text: "a".repeat(MAX_TEXT_LENGTH), stroke: "#374151", fontSize: 16,
    }));
    expect(JSON.stringify(big).length).toBeGreaterThan(MAX_DRAWING_BYTES);
    await expect(saveDrawing(big)).rejects.toThrow(/too large to save/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
