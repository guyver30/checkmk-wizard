// Load and save the shared topology-map drawing (quick 261005-eln). The file lives on the
// dashboard container's map_drawing_data volume and is served and written by nginx's
// `location = /map-drawing.json` (deploy/dashboard-nginx.conf): GET reads it, PUT replaces
// it (application/json only, 256 KB cap). Last write wins -- no ETag, no merge.
//
// The Vite dev server has no such location, so under `npm run dev` load shows the
// non-blocking error (or 404 -> empty) and save fails; the feature is exercised against
// the built image.

import {
  MAX_DRAWING_BYTES,
  drawingByteLength,
  emptyDrawing,
  sanitizeDrawing,
  serializeDrawing,
  type Drawing,
  type Shape,
} from "./mapDrawing";

export const MAP_DRAWING_URL = "/map-drawing.json";

export class MapDrawingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MapDrawingError";
  }
}

export async function loadDrawing(): Promise<Drawing> {
  let response: Response;
  try {
    response = await fetch(MAP_DRAWING_URL, { cache: "no-store", headers: { Accept: "application/json" } });
  } catch {
    throw new MapDrawingError("Could not reach the drawing store");
  }
  if (response.status === 404) return emptyDrawing();
  if (!response.ok) throw new MapDrawingError(`Could not load the drawing (HTTP ${response.status})`);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new MapDrawingError("The stored drawing is not valid JSON");
  }
  return sanitizeDrawing(body);
}

export async function saveDrawing(shapes: Shape[]): Promise<Drawing> {
  const body = serializeDrawing(shapes, new Date());
  if (drawingByteLength(body) > MAX_DRAWING_BYTES) {
    throw new MapDrawingError("Drawing is too large to save");
  }
  let response: Response;
  try {
    response = await fetch(MAP_DRAWING_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch {
    throw new MapDrawingError("Could not reach the drawing store");
  }
  if (response.status === 413) throw new MapDrawingError("Drawing is too large for the server to accept");
  if (response.status === 415) throw new MapDrawingError("The server rejected the content type");
  if (!response.ok) throw new MapDrawingError(`Could not save the drawing (HTTP ${response.status})`);
  return sanitizeDrawing(JSON.parse(body));
}
