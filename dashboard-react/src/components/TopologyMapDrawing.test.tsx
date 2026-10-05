import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TopologyMap } from "./TopologyMap";
import { instances, resetFakeNetworks } from "../test/fakeVisNetwork";
import { __resetMapDrawingStoreForTests, useMapDrawingStore } from "../store/mapDrawingStore";
import * as client from "../lib/mapDrawingClient";
import * as checkmkWrite from "../lib/checkmkWrite";
import { DRAWING_PALETTE, emptyDrawing, type Drawing, type Shape } from "../lib/mapDrawing";
import type { DevicePayload } from "../lib/types";

vi.mock("../lib/checkmkWrite", () => ({
  updateParents: vi.fn(),
  setMapPosition: vi.fn(),
  createUnmanagedSwitch: vi.fn(),
  isValidHostName: () => true,
}));
vi.mock("../lib/mapDrawingClient", () => ({
  loadDrawing: vi.fn(),
  saveDrawing: vi.fn(),
}));

const NOW_MS = Date.parse("2026-10-05T12:00:00Z");
const topologyDevices = [{ id: "h1", parents: [] }];
const statuses: Record<string, DevicePayload> = {
  h1: { id: "h1", state: "OK", timestamp: new Date(NOW_MS - 5000).toISOString(), device_type: "NetworkDevice" },
};
const BLUE = DRAWING_PALETTE[1].color;

const rect = (over: Partial<Extract<Shape, { type: "rect" }>> = {}): Shape => ({
  id: "r1", type: "rect", x: 0, y: 0, w: 100, h: 50, stroke: BLUE, fill: null, strokeWidth: 2, ...over,
});
const label = (): Shape => ({ id: "t1", type: "text", x: 0, y: 0, text: "Floor 1", stroke: BLUE, fontSize: 16 });

const store = () => useMapDrawingStore.getState();

function tree(props: Partial<React.ComponentProps<typeof TopologyMap>>) {
  return (
    <MemoryRouter>
      <TopologyMap topologyDevices={topologyDevices} statuses={statuses} nowMs={NOW_MS} {...props} />
    </MemoryRouter>
  );
}

async function renderMap(props: Partial<React.ComponentProps<typeof TopologyMap>> = {}) {
  const view = render(tree(props));
  await waitFor(() => expect(store().loading).toBe(false));
  return {
    ...view,
    rerenderMap: (next: Partial<React.ComponentProps<typeof TopologyMap>>) => view.rerender(tree(next)),
  };
}

const canvas = () => screen.getByTestId("topology-map-canvas");

function recordingCtx() {
  const log: string[] = [];
  const fn = (name: string) => vi.fn(() => void log.push(name));
  const ctx = {
    save: fn("save"), restore: fn("restore"), beginPath: fn("beginPath"), moveTo: fn("moveTo"),
    lineTo: fn("lineTo"), stroke: fn("stroke"), fill: fn("fill"), strokeRect: fn("strokeRect"),
    fillRect: fn("fillRect"), ellipse: fn("ellipse"), fillText: fn("fillText"), arc: fn("arc"),
    globalAlpha: 1, lineWidth: 1, strokeStyle: "", fillStyle: "", font: "", textBaseline: "",
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, log };
}

beforeEach(() => {
  resetFakeNetworks();
  __resetMapDrawingStoreForTests();
  vi.mocked(checkmkWrite.setMapPosition).mockReset();
  vi.mocked(client.loadDrawing).mockReset().mockResolvedValue(emptyDrawing());
  vi.mocked(client.saveDrawing).mockReset();
});

describe("TopologyMap drawing layer", () => {
  it("paints the stored shapes in beforeDrawing, after the grid, and never in afterDrawing", async () => {
    const drawing: Drawing = { version: 1, updated_at: null, shapes: [rect()] };
    vi.mocked(client.loadDrawing).mockResolvedValue(drawing);
    render(tree({}));
    await waitFor(() => expect(store().draft).toHaveLength(1));

    const before = recordingCtx();
    act(() => instances[0].emit("beforeDrawing", before.ctx));
    const gridStroke = before.log.indexOf("stroke");
    const shapeStroke = before.log.indexOf("strokeRect");
    expect(gridStroke).toBeGreaterThanOrEqual(0);
    expect(shapeStroke).toBeGreaterThan(gridStroke);

    const after = recordingCtx();
    act(() => instances[0].emit("afterDrawing", after.ctx));
    expect(after.log).not.toContain("strokeRect");
  });

  it("has no toolbar outside edit mode and does not take pointer events", async () => {
    await renderMap({ editMode: false });
    expect(screen.queryByRole("toolbar", { name: "Drawing tools" })).not.toBeInTheDocument();
    store().setTool("rect");
    const notPrevented = fireEvent.pointerDown(canvas(), { clientX: 100, clientY: 100, pointerId: 1 });
    expect(notPrevented).toBe(true);
    expect(store().draft).toEqual([]);
  });

  it("shows tools, palette, Save and Revert in edit mode, with Save disabled until a change", async () => {
    await renderMap({ editMode: true });
    expect(screen.getByRole("toolbar", { name: "Drawing tools" })).toBeInTheDocument();
    for (const name of ["Hosts", "Select", "Rectangle", "Ellipse", "Line", "Text"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Stroke Blue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No fill" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Revert" })).toBeDisabled();
    expect(screen.queryByText("Unsaved drawing changes")).not.toBeInTheDocument();

    act(() => store().addShape(rect()));
    expect(screen.getByText("Unsaved drawing changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("creates a rectangle by dragging on empty canvas with the rectangle tool", async () => {
    await renderMap({ editMode: true });
    fireEvent.click(screen.getByRole("button", { name: "Rectangle" }));
    const notPrevented = fireEvent.pointerDown(canvas(), { clientX: 100, clientY: 100, pointerId: 1 });
    expect(notPrevented).toBe(false);
    fireEvent.pointerMove(window, { clientX: 200, clientY: 175, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });
    expect(store().draft).toHaveLength(1);
    expect(store().draft[0]).toMatchObject({ type: "rect", x: 100, y: 100, w: 100, h: 75 });
    expect(checkmkWrite.setMapPosition).not.toHaveBeenCalled();
  });

  it("drops a rectangle created by a plain click", async () => {
    await renderMap({ editMode: true });
    fireEvent.click(screen.getByRole("button", { name: "Rectangle" }));
    fireEvent.pointerDown(canvas(), { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });
    expect(store().draft).toEqual([]);
  });

  it("leaves the pointer to vis-network when a host node is under it", async () => {
    await renderMap({ editMode: true });
    fireEvent.click(screen.getByRole("button", { name: "Rectangle" }));
    instances[0].nodeAtResult = "h1";
    const notPrevented = fireEvent.pointerDown(canvas(), { clientX: 100, clientY: 100, pointerId: 1 });
    expect(notPrevented).toBe(true);
    expect(store().draft).toEqual([]);
  });

  it("never takes empty-canvas pointer events with the Hosts tool", async () => {
    await renderMap({ editMode: true });
    expect(store().tool).toBe("none");
    const notPrevented = fireEvent.pointerDown(canvas(), { clientX: 100, clientY: 100, pointerId: 1 });
    expect(notPrevented).toBe(true);
    expect(store().draft).toEqual([]);
  });

  it("moves a shape with the Select tool", async () => {
    await renderMap({ editMode: true });
    act(() => store().addShape(rect()));
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    const notPrevented = fireEvent.pointerDown(canvas(), { clientX: 50, clientY: 25, pointerId: 1 });
    expect(notPrevented).toBe(false);
    fireEvent.pointerMove(window, { clientX: 100, clientY: 25, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });
    expect(store().draft[0]).toMatchObject({ x: 50, y: 0, w: 100, h: 50 });
    expect(store().selectedId).toBe("r1");
  });

  it("creates a text label that the toolbar input can edit", async () => {
    await renderMap({ editMode: true });
    fireEvent.click(screen.getByRole("button", { name: "Text" }));
    fireEvent.pointerDown(canvas(), { clientX: 60, clientY: 40, pointerId: 1 });
    expect(store().draft[0]).toMatchObject({ type: "text", text: "Label" });
    expect(store().tool).toBe("select");
    fireEvent.change(screen.getByLabelText("Label text"), { target: { value: "<b>Floor 2</b>" } });
    expect(store().draft[0]).toMatchObject({ text: "<b>Floor 2</b>" });
  });

  it("Revert restores the saved drawing", async () => {
    await renderMap({ editMode: true });
    act(() => store().addShape(rect()));
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    expect(store().draft).toEqual([]);
    expect(screen.queryByText("Unsaved drawing changes")).not.toBeInTheDocument();
  });

  it("Save clears the indicator on success and keeps the draft with an error on failure", async () => {
    await renderMap({ editMode: true });
    act(() => store().addShape(rect()));
    vi.mocked(client.saveDrawing).mockRejectedValueOnce(new Error("boom"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(store().draft).toHaveLength(1);
    expect(screen.getByText("Unsaved drawing changes")).toBeInTheDocument();

    vi.mocked(client.saveDrawing).mockResolvedValueOnce({ version: 1, updated_at: "now", shapes: [rect()] });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByText("Unsaved drawing changes")).not.toBeInTheDocument());
    expect(client.saveDrawing).toHaveBeenCalledTimes(2);
  });

  it("deletes the selected shape from the button and from the Delete key, but not while typing", async () => {
    await renderMap({ editMode: true });
    act(() => {
      store().addShape(rect());
      store().select("r1");
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(store().draft).toEqual([]);

    act(() => {
      store().addShape(label());
      store().select("t1");
    });
    fireEvent.keyDown(screen.getByLabelText("Label text"), { key: "Delete" });
    expect(store().draft).toHaveLength(1);
    fireEvent.keyDown(document.body, { key: "Delete" });
    expect(store().draft).toEqual([]);
  });

  it("shows a dismissible, non-blocking message when the load fails", async () => {
    vi.mocked(client.loadDrawing).mockRejectedValue(new Error("HTTP 500"));
    await renderMap({});
    expect(await screen.findByRole("status")).toHaveTextContent("HTTP 500");
    expect(canvas()).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss drawing message" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("redraws the network when the drawing changes", async () => {
    await renderMap({ editMode: true });
    const before = instances[0].redrawCount;
    act(() => store().addShape(rect()));
    expect(instances[0].redrawCount).toBeGreaterThan(before);
  });

  it("keeps the draft and keeps rendering it when edit mode turns off", async () => {
    const { rerenderMap } = await renderMap({ editMode: true });
    fireEvent.click(screen.getByRole("button", { name: "Rectangle" }));
    act(() => store().addShape(rect()));
    rerenderMap({ editMode: false });
    expect(screen.queryByRole("toolbar", { name: "Drawing tools" })).not.toBeInTheDocument();
    expect(store().draft).toHaveLength(1);
    expect(store().tool).toBe("none");
    const { ctx, log } = recordingCtx();
    act(() => instances[0].emit("beforeDrawing", ctx));
    expect(log).toContain("strokeRect");
  });

  it("registers a beforeunload guard only while the draft is dirty", async () => {
    await renderMap({ editMode: true });
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    act(() => store().addShape(rect()));
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });
});
