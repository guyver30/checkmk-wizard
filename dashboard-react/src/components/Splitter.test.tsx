import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Splitter } from "./Splitter";

// jsdom does not implement Element.setPointerCapture/releasePointerCapture -- stub both as
// no-ops on the prototype so pointer-event tests below don't throw. This is a test-env gap,
// not a bug in Splitter itself.
beforeAll(() => {
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

describe("Splitter", () => {
  it("renders the full ARIA separator contract", () => {
    render(
      <Splitter orientation="vertical" value={320} min={200} max={640} label="Resize device tree" onResize={vi.fn()} />,
    );
    const el = screen.getByRole("separator");
    expect(el).toHaveAttribute("aria-orientation", "vertical");
    expect(el).toHaveAttribute("aria-valuenow", "320");
    expect(el).toHaveAttribute("aria-valuemin", "200");
    expect(el).toHaveAttribute("aria-valuemax", "640");
    expect(el).toHaveAttribute("aria-label", "Resize device tree");
    expect(el).toHaveAttribute("tabIndex", "0");
  });

  it("resizes on ArrowRight/ArrowLeft for a vertical separator", () => {
    const onResize = vi.fn();
    render(
      <Splitter orientation="vertical" value={320} min={200} max={640} step={16} label="tree" onResize={onResize} />,
    );
    const el = screen.getByRole("separator");
    fireEvent.keyDown(el, { key: "ArrowRight" });
    expect(onResize).toHaveBeenCalledWith(336);
    fireEvent.keyDown(el, { key: "ArrowLeft" });
    expect(onResize).toHaveBeenCalledWith(304);
  });

  it("resizes on ArrowUp/ArrowDown for a horizontal separator", () => {
    const onResize = vi.fn();
    render(
      <Splitter
        orientation="horizontal"
        value={260}
        min={120}
        max={600}
        step={16}
        label="events"
        onResize={onResize}
      />,
    );
    const el = screen.getByRole("separator");
    fireEvent.keyDown(el, { key: "ArrowDown" });
    expect(onResize).toHaveBeenCalledWith(276);
    fireEvent.keyDown(el, { key: "ArrowUp" });
    expect(onResize).toHaveBeenCalledWith(244);
  });

  it("clamps ArrowLeft at the minimum so it never goes below min", () => {
    const onResize = vi.fn();
    render(
      <Splitter orientation="vertical" value={200} min={200} max={640} step={16} label="tree" onResize={onResize} />,
    );
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowLeft" });
    expect(onResize).toHaveBeenCalledWith(200);
  });

  it("clamps ArrowRight at the maximum so it never exceeds max", () => {
    const onResize = vi.fn();
    render(
      <Splitter orientation="vertical" value={640} min={200} max={640} step={16} label="tree" onResize={onResize} />,
    );
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    expect(onResize).toHaveBeenCalledWith(640);
  });

  it("Home and End jump to min and max respectively", () => {
    const onResize = vi.fn();
    render(
      <Splitter orientation="vertical" value={400} min={200} max={640} label="tree" onResize={onResize} />,
    );
    const el = screen.getByRole("separator");
    fireEvent.keyDown(el, { key: "Home" });
    expect(onResize).toHaveBeenCalledWith(200);
    fireEvent.keyDown(el, { key: "End" });
    expect(onResize).toHaveBeenCalledWith(640);
  });

  it("ignores keys that are not arrow/Home/End", () => {
    const onResize = vi.fn();
    render(
      <Splitter orientation="vertical" value={400} min={200} max={640} label="tree" onResize={onResize} />,
    );
    fireEvent.keyDown(screen.getByRole("separator"), { key: "Enter" });
    expect(onResize).not.toHaveBeenCalled();
  });

  it("calls onResizeCommit exactly once across a pointerdown/pointermove/pointerup sequence", () => {
    const onResize = vi.fn();
    const onResizeCommit = vi.fn();
    render(
      <Splitter
        orientation="vertical"
        value={320}
        min={200}
        max={640}
        label="tree"
        onResize={onResize}
        onResizeCommit={onResizeCommit}
      />,
    );
    const el = screen.getByRole("separator");
    fireEvent.pointerDown(el, { clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(el, { clientX: 110, pointerId: 1 });
    fireEvent.pointerMove(el, { clientX: 120, pointerId: 1 });
    fireEvent.pointerMove(el, { clientX: 130, pointerId: 1 });
    fireEvent.pointerUp(el, { clientX: 130, pointerId: 1 });
    expect(onResizeCommit).toHaveBeenCalledTimes(1);
    expect(onResizeCommit).toHaveBeenCalledWith(350);
  });
});
