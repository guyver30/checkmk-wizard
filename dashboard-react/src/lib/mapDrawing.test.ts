import { describe, expect, it, vi } from "vitest";
import {
  COORD_LIMIT,
  DEFAULT_STROKE,
  DRAWING_PALETTE,
  MAX_DRAWING_BYTES,
  MAX_SHAPES,
  MAX_TEXT_LENGTH,
  SHAPE_SNAP,
  drawShapes,
  drawingByteLength,
  emptyDrawing,
  hitTest,
  moveShape,
  resizeShape,
  sanitizeDrawing,
  serializeDrawing,
  type Shape,
} from "./mapDrawing";

const BLUE = DRAWING_PALETTE[1].color;

function rect(over: Partial<Extract<Shape, { type: "rect" }>> = {}): Shape {
  return { id: "r1", type: "rect", x: 0, y: 0, w: 100, h: 50, stroke: BLUE, fill: null, strokeWidth: 2, ...over };
}

describe("sanitizeDrawing", () => {
  it.each([null, undefined, 5, "x", [], { version: 2, shapes: [] }, {}])(
    "returns an empty drawing for %j",
    (input) => {
      expect(sanitizeDrawing(input)).toEqual(emptyDrawing());
    },
  );

  it("drops unknown types, bad ids and non-finite numbers", () => {
    const d = sanitizeDrawing({
      version: 1,
      shapes: [
        { id: "a", type: "star", x: 0, y: 0 },
        { id: 7, type: "rect", x: 0, y: 0, w: 1, h: 1 },
        { id: "b", type: "rect", x: Number.NaN, y: 0, w: 1, h: 1 },
        { id: "c", type: "rect", x: "3", y: 0, w: 1, h: 1 },
        { id: "ok", type: "rect", x: 1, y: 2, w: 3, h: 4 },
        null,
      ],
    });
    expect(d.shapes.map((s) => s.id)).toEqual(["ok"]);
  });

  it("caps the number of shapes", () => {
    const shapes = Array.from({ length: MAX_SHAPES + 20 }, (_, i) => ({
      id: `s${i}`, type: "line", x1: 0, y1: 0, x2: 1, y2: 1,
    }));
    expect(sanitizeDrawing({ version: 1, shapes }).shapes).toHaveLength(MAX_SHAPES);
  });

  it("clamps coordinates, sizes, stroke width and font size", () => {
    const d = sanitizeDrawing({
      version: 1,
      shapes: [
        { id: "r", type: "rect", x: 1e9, y: -1e9, w: -5, h: 1e9, strokeWidth: 99 },
        { id: "t", type: "text", x: 0, y: 0, text: "x", fontSize: 17 },
      ],
    });
    const r = d.shapes[0] as Extract<Shape, { type: "rect" }>;
    expect(r.x).toBe(COORD_LIMIT);
    expect(r.y).toBe(-COORD_LIMIT);
    expect(r.w).toBe(1);
    expect(r.h).toBe(COORD_LIMIT);
    expect(r.strokeWidth).toBe(12);
    const t = d.shapes[1] as Extract<Shape, { type: "text" }>;
    expect(t.fontSize).toBe(16);
  });

  it("falls back to the default stroke and no fill for off-palette colours", () => {
    const d = sanitizeDrawing({
      version: 1,
      shapes: [{ id: "r", type: "rect", x: 0, y: 0, w: 5, h: 5, stroke: "url(javascript:1)", fill: "red" }],
    });
    const r = d.shapes[0] as Extract<Shape, { type: "rect" }>;
    expect(r.stroke).toBe(DEFAULT_STROKE);
    expect(r.fill).toBeNull();
  });

  it("keeps palette colours", () => {
    const d = sanitizeDrawing({
      version: 1,
      shapes: [{ id: "r", type: "ellipse", x: 0, y: 0, w: 5, h: 5, stroke: BLUE, fill: BLUE }],
    });
    const r = d.shapes[0] as Extract<Shape, { type: "ellipse" }>;
    expect(r.stroke).toBe(BLUE);
    expect(r.fill).toBe(BLUE);
  });

  it("strips control characters, caps text and keeps markup as literal characters", () => {
    const long = "a".repeat(MAX_TEXT_LENGTH + 50);
    const d = sanitizeDrawing({
      version: 1,
      shapes: [
        { id: "t1", type: "text", x: 0, y: 0, text: "<script>alert(1)</script>\u0000\n" },
        { id: "t2", type: "text", x: 0, y: 0, text: long },
        { id: "t3", type: "text", x: 0, y: 0, text: 42 },
      ],
    });
    const texts = d.shapes.map((s) => (s as Extract<Shape, { type: "text" }>).text);
    expect(texts[0]).toBe("<script>alert(1)</script>");
    expect(texts[1]).toHaveLength(MAX_TEXT_LENGTH);
    expect(texts[2]).toBe("42");
  });
});

describe("serializeDrawing", () => {
  it("round-trips through sanitizeDrawing", () => {
    const shapes: Shape[] = [
      rect({ fill: BLUE }),
      { id: "e", type: "ellipse", x: 5, y: 5, w: 10, h: 20, stroke: DEFAULT_STROKE, fill: null, strokeWidth: 3 },
      { id: "l", type: "line", x1: 0, y1: 0, x2: 50, y2: 75, stroke: BLUE, strokeWidth: 2 },
      { id: "t", type: "text", x: 1, y: 2, text: "Floor 3", stroke: BLUE, fontSize: 24 },
    ];
    const now = new Date("2026-10-05T10:00:00.000Z");
    const json = serializeDrawing(shapes, now);
    const parsed = JSON.parse(json);
    expect(parsed.version).toBe(1);
    expect(parsed.updated_at).toBe("2026-10-05T10:00:00.000Z");
    expect(sanitizeDrawing(parsed).shapes).toEqual(shapes);
  });

  it("measures byte length in UTF-8 bytes", () => {
    expect(drawingByteLength("abc")).toBe(3);
    expect(drawingByteLength("ä")).toBe(2);
    expect(MAX_DRAWING_BYTES).toBeLessThan(256 * 1024);
  });
});

describe("hitTest", () => {
  it("returns the topmost (last) shape", () => {
    const shapes = [rect({ id: "a" }), rect({ id: "b" })];
    expect(hitTest(shapes, { x: 50, y: 25 }, 6, null)).toEqual({ id: "b", handle: "body" });
  });

  it("hits inside and on the border of a rect, misses outside", () => {
    const shapes = [rect()];
    expect(hitTest(shapes, { x: 50, y: 25 }, 6, null)?.id).toBe("r1");
    expect(hitTest(shapes, { x: 103, y: 25 }, 6, null)?.id).toBe("r1");
    expect(hitTest(shapes, { x: 200, y: 25 }, 6, null)).toBeNull();
  });

  it("hits an ellipse inside but not in its bounding-box corner", () => {
    const e: Shape = { id: "e", type: "ellipse", x: 0, y: 0, w: 100, h: 100, stroke: BLUE, fill: null, strokeWidth: 2 };
    expect(hitTest([e], { x: 50, y: 50 }, 6, null)?.id).toBe("e");
    expect(hitTest([e], { x: 3, y: 3 }, 6, null)).toBeNull();
  });

  it("hits a line within tolerance of the segment", () => {
    const l: Shape = { id: "l", type: "line", x1: 0, y1: 0, x2: 100, y2: 0, stroke: BLUE, strokeWidth: 2 };
    expect(hitTest([l], { x: 50, y: 4 }, 6, null)?.id).toBe("l");
    expect(hitTest([l], { x: 50, y: 20 }, 6, null)).toBeNull();
    expect(hitTest([l], { x: 150, y: 0 }, 6, null)).toBeNull();
  });

  it("hits a text inside its approximate box", () => {
    const t: Shape = { id: "t", type: "text", x: 10, y: 10, text: "abcde", stroke: BLUE, fontSize: 16 };
    expect(hitTest([t], { x: 20, y: 18 }, 0, null)?.id).toBe("t");
    expect(hitTest([t], { x: 500, y: 18 }, 0, null)).toBeNull();
  });

  it("gives selected-shape handles priority over bodies", () => {
    const shapes = [rect({ id: "a" }), rect({ id: "b", x: 90, y: 40, w: 100, h: 50 })];
    // (100,50) is the se corner of a and inside b; selecting a returns a's handle.
    expect(hitTest(shapes, { x: 100, y: 50 }, 6, "a")).toEqual({ id: "a", handle: "se" });
    expect(hitTest(shapes, { x: 100, y: 50 }, 6, null)).toEqual({ id: "b", handle: "body" });
  });

  it("exposes line endpoints as handles", () => {
    const l: Shape = { id: "l", type: "line", x1: 0, y1: 0, x2: 100, y2: 0, stroke: BLUE, strokeWidth: 2 };
    expect(hitTest([l], { x: 100, y: 1 }, 6, "l")).toEqual({ id: "l", handle: "p2" });
    expect(hitTest([l], { x: 1, y: 0 }, 6, "l")).toEqual({ id: "l", handle: "p1" });
  });
});

describe("moveShape / resizeShape", () => {
  it("moves with the anchor snapped to SHAPE_SNAP", () => {
    expect(SHAPE_SNAP).toBe(25);
    const m = moveShape(rect(), 30, 10) as Extract<Shape, { type: "rect" }>;
    expect([m.x, m.y]).toEqual([25, 0]);
    const l: Shape = { id: "l", type: "line", x1: 0, y1: 0, x2: 40, y2: 10, stroke: BLUE, strokeWidth: 2 };
    const ml = moveShape(l, 50, 50) as Extract<Shape, { type: "line" }>;
    expect([ml.x1, ml.y1, ml.x2, ml.y2]).toEqual([50, 50, 90, 60]);
  });

  it("resizes by moving the dragged corner and normalises negative sizes", () => {
    const se = resizeShape(rect(), "se", { x: 160, y: 80 }) as Extract<Shape, { type: "rect" }>;
    expect([se.x, se.y, se.w, se.h]).toEqual([0, 0, 150, 75]);
    const nw = resizeShape(rect(), "nw", { x: 125, y: 75 }) as Extract<Shape, { type: "rect" }>;
    // Dragged past the opposite corner: normalised, never negative.
    expect([nw.x, nw.y, nw.w, nw.h]).toEqual([100, 50, 25, 25]);
  });

  it("drags line endpoints with snap", () => {
    const l: Shape = { id: "l", type: "line", x1: 0, y1: 0, x2: 100, y2: 0, stroke: BLUE, strokeWidth: 2 };
    const r = resizeShape(l, "p2", { x: 130, y: 61 }) as Extract<Shape, { type: "line" }>;
    expect([r.x1, r.y1, r.x2, r.y2]).toEqual([0, 0, 125, 50]);
  });

  it("leaves text unchanged on resize", () => {
    const t: Shape = { id: "t", type: "text", x: 0, y: 0, text: "x", stroke: BLUE, fontSize: 16 };
    expect(resizeShape(t, "se", { x: 90, y: 90 })).toEqual(t);
  });
});

describe("drawShapes", () => {
  function recordingCtx() {
    const calls: string[] = [];
    const rec = (name: string) => vi.fn(() => void calls.push(name));
    const ctx = {
      save: rec("save"), restore: rec("restore"), beginPath: rec("beginPath"),
      moveTo: rec("moveTo"), lineTo: rec("lineTo"), stroke: rec("stroke"), fill: rec("fill"),
      strokeRect: rec("strokeRect"), fillRect: rec("fillRect"), ellipse: rec("ellipse"),
      fillText: rec("fillText"),
      globalAlpha: 1, lineWidth: 1, strokeStyle: "", fillStyle: "", font: "", textBaseline: "",
    };
    return { ctx: ctx as unknown as CanvasRenderingContext2D, calls, raw: ctx };
  }

  it("draws shapes in array order, text via fillText", () => {
    const { ctx, calls, raw } = recordingCtx();
    const shapes: Shape[] = [
      rect(),
      { id: "e", type: "ellipse", x: 0, y: 0, w: 10, h: 10, stroke: BLUE, fill: BLUE, strokeWidth: 2 },
      { id: "l", type: "line", x1: 0, y1: 0, x2: 5, y2: 5, stroke: BLUE, strokeWidth: 2 },
      { id: "t", type: "text", x: 0, y: 0, text: "<b>hi</b>", stroke: BLUE, fontSize: 16 },
    ];
    drawShapes(ctx, shapes, null, 1);
    const order = calls.filter((c) => ["strokeRect", "ellipse", "lineTo", "fillText"].includes(c));
    expect(order).toEqual(["strokeRect", "ellipse", "lineTo", "fillText"]);
    expect(raw.fillText).toHaveBeenCalledWith("<b>hi</b>", 0, 0);
  });

  it("draws handles only for the selected shape", () => {
    const a = recordingCtx();
    drawShapes(a.ctx, [rect()], null, 1);
    const b = recordingCtx();
    drawShapes(b.ctx, [rect()], "r1", 1);
    expect(b.calls.filter((c) => c === "fillRect").length).toBeGreaterThan(
      a.calls.filter((c) => c === "fillRect").length,
    );
  });
});
