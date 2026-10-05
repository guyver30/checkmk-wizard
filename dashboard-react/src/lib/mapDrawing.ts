// Drawing layer for the topology map (quick 261005-eln; groundwork for the location
// work that follows): a small set of shapes (rectangle, ellipse, line, text) kept in
// vis-network's canvas coordinate space, so they pan and zoom with the map and sit in the
// same space as the node grid. Everything here is pure geometry and canvas drawing --
// no DOM access besides the ctx it is handed -- so it can be tested without a browser.
//
// Trust: the JSON file is read from a volume anyone on the closed network can overwrite
// (nginx accepts an open PUT on /map-drawing.json), so sanitizeDrawing treats it as
// untrusted. Text is only ever painted with ctx.fillText (and shown in a React-controlled
// input), never as HTML.

export const DRAWING_VERSION = 1;
export const MAX_SHAPES = 500;
export const MAX_TEXT_LENGTH = 200;
export const MAX_ID_LENGTH = 64;
export const COORD_LIMIT = 100000;
// Kept below nginx's client_max_body_size (256k) so the client rejects first.
export const MAX_DRAWING_BYTES = 200000;
// Half of MAP_SNAP_SPACING (50): floor labels need finer placement than hosts, while
// lines still land on the node grid.
export const SHAPE_SNAP = 25;
export const FONT_SIZES = [12, 16, 24, 36] as const;

export const DRAWING_PALETTE = [
  { name: "Dark grey", color: "#374151" },
  { name: "Blue", color: "#2563eb" },
  { name: "Green", color: "#16a34a" },
  { name: "Amber", color: "#d97706" },
  { name: "Red", color: "#dc2626" },
  { name: "Purple", color: "#7c3aed" },
] as const;
export const DEFAULT_STROKE: string = DRAWING_PALETTE[0].color;

const DEFAULT_STROKE_WIDTH = 2;
const DEFAULT_FONT_SIZE = 16;
const FILL_ALPHA = 0.15; // low alpha so host nodes stay visible through filled shapes
const FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const TEXT_WIDTH_FACTOR = 0.6; // approximate glyph width per font-size unit (no measureText)
const HANDLE_SIZE = 8; // screen pixels

type Base = { id: string };
export type RectShape = Base & {
  type: "rect"; x: number; y: number; w: number; h: number;
  stroke: string; fill: string | null; strokeWidth: number;
};
export type EllipseShape = Base & {
  type: "ellipse"; x: number; y: number; w: number; h: number;
  stroke: string; fill: string | null; strokeWidth: number;
};
export type LineShape = Base & {
  type: "line"; x1: number; y1: number; x2: number; y2: number;
  stroke: string; strokeWidth: number;
};
export type TextShape = Base & {
  type: "text"; x: number; y: number; text: string; stroke: string; fontSize: number;
};
export type Shape = RectShape | EllipseShape | LineShape | TextShape;

export interface Drawing {
  version: 1;
  updated_at: string | null;
  shapes: Shape[];
}

export type Handle = "body" | "nw" | "ne" | "sw" | "se" | "p1" | "p2";
export interface Hit { id: string; handle: Handle }
export interface Point { x: number; y: number }

export function emptyDrawing(): Drawing {
  return { version: DRAWING_VERSION, updated_at: null, shapes: [] };
}

export function newShapeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function snapShapeValue(value: number): number {
  return Math.round(value / SHAPE_SNAP) * SHAPE_SNAP;
}

// ---------------------------------------------------------------- sanitising

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finite(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function strokeOf(v: unknown): string {
  return DRAWING_PALETTE.some((p) => p.color === v) ? (v as string) : DEFAULT_STROKE;
}

function fillOf(v: unknown): string | null {
  return DRAWING_PALETTE.some((p) => p.color === v) ? (v as string) : null;
}

function widthOf(v: unknown): number {
  const n = finite(v);
  return n === null ? DEFAULT_STROKE_WIDTH : clamp(Math.round(n), 1, 12);
}

function cleanText(v: unknown): string {
  const raw = typeof v === "string" ? v : v === undefined || v === null ? "" : String(v);
  let out = "";
  for (const ch of raw) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) continue;
    out += ch;
  }
  return out.slice(0, MAX_TEXT_LENGTH);
}

function coord(v: unknown): number | null {
  const n = finite(v);
  return n === null ? null : clamp(n, -COORD_LIMIT, COORD_LIMIT);
}

function size(v: unknown): number | null {
  const n = finite(v);
  return n === null ? null : clamp(n, 1, COORD_LIMIT);
}

function sanitizeShape(raw: unknown): Shape | null {
  if (!isRecord(raw) || typeof raw.id !== "string" || raw.id === "" || raw.id.length > MAX_ID_LENGTH) return null;
  const id = raw.id;
  switch (raw.type) {
    case "rect":
    case "ellipse": {
      const x = coord(raw.x), y = coord(raw.y), w = size(raw.w), h = size(raw.h);
      if (x === null || y === null || w === null || h === null) return null;
      return {
        id, type: raw.type, x, y, w, h,
        stroke: strokeOf(raw.stroke), fill: fillOf(raw.fill), strokeWidth: widthOf(raw.strokeWidth),
      };
    }
    case "line": {
      const x1 = coord(raw.x1), y1 = coord(raw.y1), x2 = coord(raw.x2), y2 = coord(raw.y2);
      if (x1 === null || y1 === null || x2 === null || y2 === null) return null;
      return { id, type: "line", x1, y1, x2, y2, stroke: strokeOf(raw.stroke), strokeWidth: widthOf(raw.strokeWidth) };
    }
    case "text": {
      const x = coord(raw.x), y = coord(raw.y);
      if (x === null || y === null) return null;
      const fs = (FONT_SIZES as readonly unknown[]).includes(raw.fontSize)
        ? (raw.fontSize as number)
        : DEFAULT_FONT_SIZE;
      return { id, type: "text", x, y, text: cleanText(raw.text), stroke: strokeOf(raw.stroke), fontSize: fs };
    }
    default:
      return null;
  }
}

export function sanitizeDrawing(input: unknown): Drawing {
  if (!isRecord(input) || input.version !== DRAWING_VERSION || !Array.isArray(input.shapes)) {
    return emptyDrawing();
  }
  const shapes: Shape[] = [];
  const seen = new Set<string>();
  for (const raw of input.shapes) {
    if (shapes.length >= MAX_SHAPES) break;
    const s = sanitizeShape(raw);
    if (!s || seen.has(s.id)) continue;
    seen.add(s.id);
    shapes.push(s);
  }
  const updated = typeof input.updated_at === "string" ? input.updated_at.slice(0, 40) : null;
  return { version: DRAWING_VERSION, updated_at: updated, shapes };
}

export function serializeDrawing(shapes: Shape[], now: Date): string {
  return JSON.stringify({ version: DRAWING_VERSION, updated_at: now.toISOString(), shapes });
}

export function drawingByteLength(json: string): number {
  return new TextEncoder().encode(json).length;
}

// ---------------------------------------------------------------- hit testing

function textBox(s: TextShape): { w: number; h: number } {
  return { w: Math.max(1, s.text.length) * TEXT_WIDTH_FACTOR * s.fontSize, h: s.fontSize };
}

function distToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2, 0, 1);
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

function handlePoints(s: Shape): { handle: Handle; x: number; y: number }[] {
  switch (s.type) {
    case "rect":
    case "ellipse":
      return [
        { handle: "nw", x: s.x, y: s.y },
        { handle: "ne", x: s.x + s.w, y: s.y },
        { handle: "sw", x: s.x, y: s.y + s.h },
        { handle: "se", x: s.x + s.w, y: s.y + s.h },
      ];
    case "line":
      return [
        { handle: "p1", x: s.x1, y: s.y1 },
        { handle: "p2", x: s.x2, y: s.y2 },
      ];
    default:
      return [];
  }
}

function bodyHit(s: Shape, p: Point, tol: number): boolean {
  switch (s.type) {
    case "rect":
      return p.x >= s.x - tol && p.x <= s.x + s.w + tol && p.y >= s.y - tol && p.y <= s.y + s.h + tol;
    case "ellipse": {
      const rx = s.w / 2 + tol, ry = s.h / 2 + tol;
      const nx = (p.x - (s.x + s.w / 2)) / rx, ny = (p.y - (s.y + s.h / 2)) / ry;
      return nx * nx + ny * ny <= 1;
    }
    case "line":
      return distToSegment(p, { x: s.x1, y: s.y1 }, { x: s.x2, y: s.y2 }) <= tol;
    case "text": {
      const b = textBox(s);
      return p.x >= s.x - tol && p.x <= s.x + b.w + tol && p.y >= s.y - tol && p.y <= s.y + b.h + tol;
    }
  }
}

export function hitTest(
  shapes: Shape[],
  point: Point,
  tolerance: number,
  selectedId: string | null,
): Hit | null {
  const selected = selectedId ? shapes.find((s) => s.id === selectedId) : undefined;
  if (selected) {
    for (const h of handlePoints(selected)) {
      if (Math.hypot(point.x - h.x, point.y - h.y) <= tolerance) {
        return { id: selected.id, handle: h.handle };
      }
    }
  }
  for (let i = shapes.length - 1; i >= 0; i--) {
    if (bodyHit(shapes[i], point, tolerance)) return { id: shapes[i].id, handle: "body" };
  }
  return null;
}

// ---------------------------------------------------------------- move / resize

function anchorOf(s: Shape): Point {
  return s.type === "line" ? { x: s.x1, y: s.y1 } : { x: s.x, y: s.y };
}

// The shape's anchor (top-left, or the first line endpoint) snaps to SHAPE_SNAP and the
// whole shape moves by the resulting delta, so a shape never distorts while it moves.
export function moveShape(s: Shape, dx: number, dy: number): Shape {
  const a = anchorOf(s);
  const ex = snapShapeValue(a.x + dx) - a.x;
  const ey = snapShapeValue(a.y + dy) - a.y;
  if (s.type === "line") {
    return { ...s, x1: s.x1 + ex, y1: s.y1 + ey, x2: s.x2 + ex, y2: s.y2 + ey };
  }
  return { ...s, x: s.x + ex, y: s.y + ey };
}

export function resizeShape(s: Shape, handle: Handle, point: Point): Shape {
  const px = snapShapeValue(point.x), py = snapShapeValue(point.y);
  if (s.type === "line") {
    if (handle === "p1") return { ...s, x1: px, y1: py };
    if (handle === "p2") return { ...s, x2: px, y2: py };
    return s;
  }
  if (s.type === "text") return s;
  const fixedX = handle === "nw" || handle === "sw" ? s.x + s.w : s.x;
  const fixedY = handle === "nw" || handle === "ne" ? s.y + s.h : s.y;
  if (handle === "body" || handle === "p1" || handle === "p2") return s;
  return {
    ...s,
    x: Math.min(fixedX, px),
    y: Math.min(fixedY, py),
    w: Math.abs(px - fixedX),
    h: Math.abs(py - fixedY),
  };
}

// ---------------------------------------------------------------- rendering

export function drawShapes(
  ctx: CanvasRenderingContext2D,
  shapes: Shape[],
  selectedId: string | null,
  scale: number,
): void {
  ctx.save();
  for (const s of shapes) {
    ctx.save();
    switch (s.type) {
      case "rect":
      case "ellipse": {
        ctx.lineWidth = s.strokeWidth;
        ctx.strokeStyle = s.stroke;
        if (s.type === "rect") {
          if (s.fill) {
            ctx.globalAlpha = FILL_ALPHA;
            ctx.fillStyle = s.fill;
            ctx.fillRect(s.x, s.y, s.w, s.h);
            ctx.globalAlpha = 1;
          }
          ctx.strokeRect(s.x, s.y, s.w, s.h);
        } else {
          ctx.beginPath();
          ctx.ellipse(s.x + s.w / 2, s.y + s.h / 2, s.w / 2, s.h / 2, 0, 0, Math.PI * 2);
          if (s.fill) {
            ctx.globalAlpha = FILL_ALPHA;
            ctx.fillStyle = s.fill;
            ctx.fill();
            ctx.globalAlpha = 1;
          }
          ctx.stroke();
        }
        break;
      }
      case "line":
        ctx.lineWidth = s.strokeWidth;
        ctx.strokeStyle = s.stroke;
        ctx.beginPath();
        ctx.moveTo(s.x1, s.y1);
        ctx.lineTo(s.x2, s.y2);
        ctx.stroke();
        break;
      case "text":
        ctx.fillStyle = s.stroke;
        ctx.font = `${s.fontSize}px ${FONT_FAMILY}`;
        ctx.textBaseline = "top";
        ctx.fillText(s.text, s.x, s.y);
        break;
    }
    ctx.restore();
  }
  const selected = selectedId ? shapes.find((s) => s.id === selectedId) : undefined;
  if (selected) {
    const size = HANDLE_SIZE / scale;
    ctx.lineWidth = 1 / scale;
    ctx.strokeStyle = "#2563eb";
    ctx.fillStyle = "#ffffff";
    if (selected.type === "text") {
      const b = textBox(selected);
      ctx.strokeRect(selected.x, selected.y, b.w, b.h);
    }
    for (const h of handlePoints(selected)) {
      ctx.fillRect(h.x - size / 2, h.y - size / 2, size, size);
      ctx.strokeRect(h.x - size / 2, h.y - size / 2, size, size);
    }
  }
  ctx.restore();
}
