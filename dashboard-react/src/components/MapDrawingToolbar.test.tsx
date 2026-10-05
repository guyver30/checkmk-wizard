import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MapDrawingToolbar } from "./MapDrawingToolbar";
import { __resetMapDrawingStoreForTests, useMapDrawingStore } from "../store/mapDrawingStore";
import { DRAWING_PALETTE, type Shape } from "../lib/mapDrawing";

vi.mock("../lib/mapDrawingClient", () => ({ loadDrawing: vi.fn(), saveDrawing: vi.fn() }));

const store = () => useMapDrawingStore.getState();
const BLUE = DRAWING_PALETTE[1];
const rect: Shape = { id: "r1", type: "rect", x: 0, y: 0, w: 10, h: 10, stroke: "#374151", fill: null, strokeWidth: 2 };

beforeEach(() => __resetMapDrawingStoreForTests());

describe("MapDrawingToolbar", () => {
  it("marks the active tool with aria-pressed and switches it on click", () => {
    render(<MapDrawingToolbar />);
    expect(screen.getByRole("button", { name: "Hosts" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Ellipse" }));
    expect(store().tool).toBe("ellipse");
    expect(screen.getByRole("button", { name: "Ellipse" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Hosts" })).toHaveAttribute("aria-pressed", "false");
  });

  it("recolours the selected shape from the stroke and fill swatches", () => {
    render(<MapDrawingToolbar />);
    act(() => {
      store().addShape(rect);
      store().select("r1");
    });
    fireEvent.click(screen.getByRole("button", { name: `Stroke ${BLUE.name}` }));
    fireEvent.click(screen.getByRole("button", { name: `Fill ${BLUE.name}` }));
    expect(store().draft[0]).toMatchObject({ stroke: BLUE.color, fill: BLUE.color });
    fireEvent.click(screen.getByRole("button", { name: "No fill" }));
    expect(store().draft[0]).toMatchObject({ fill: null });
  });

  it("disables Delete without a selection and reports activity on actions", () => {
    const onActivity = vi.fn();
    render(<MapDrawingToolbar onActivity={onActivity} />);
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Line" }));
    expect(onActivity).toHaveBeenCalledTimes(1);
  });

  it("shows the text editor only for a selected text shape and caps its length", () => {
    render(<MapDrawingToolbar />);
    expect(screen.queryByLabelText("Label text")).not.toBeInTheDocument();
    act(() => {
      store().addShape({ id: "t", type: "text", x: 0, y: 0, text: "a", stroke: "#374151", fontSize: 16 });
      store().select("t");
    });
    expect(screen.getByLabelText("Label text")).toHaveAttribute("maxLength", "200");
    fireEvent.change(screen.getByLabelText("Label size"), { target: { value: "24" } });
    expect(store().draft[0]).toMatchObject({ fontSize: 24 });
  });
});
