import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThreePaneLayout } from "./ThreePaneLayout";

// jsdom does not implement Element.setPointerCapture/releasePointerCapture; Splitter calls
// them on render-bound handlers, not on mount, but the stub keeps any future pointer-driven
// assertions in this file safe too.
beforeAll(() => {
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

describe("ThreePaneLayout", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders all three named pane regions", () => {
    render(
      <ThreePaneLayout
        tree={<p>Device tree content</p>}
        centreTop={<div>centre top</div>}
        centreBottom={<p>Event history content</p>}
      />,
    );
    expect(screen.getByText("Device tree content")).toBeInTheDocument();
    expect(screen.getByText("centre top")).toBeInTheDocument();
    expect(screen.getByText("Event history content")).toBeInTheDocument();
  });

  it("renders exactly two separators, one vertical and one horizontal", () => {
    render(<ThreePaneLayout tree={<p>tree</p>} centreTop={<p>top</p>} centreBottom={<p>bottom</p>} />);
    const separators = screen.getAllByRole("separator");
    expect(separators).toHaveLength(2);
    const orientations = separators.map((el) => el.getAttribute("aria-orientation"));
    expect(orientations).toContain("vertical");
    expect(orientations).toContain("horizontal");
  });

  // Regression: live UAT (2026-09-23) found the event-history divider working backwards --
  // dragging it DOWN shrank the map instead of growing it, because sizes.events is the BOTTOM
  // pane's own height while Splitter's contract makes dragging down always increase whatever
  // value it's given. Fixed by mirroring value/onResize in ThreePaneLayout so the divider
  // follows the natural "boundary tracks the cursor" convention for a divider above a
  // fixed-size bottom pane.
  it("dragging the event-history separator down grows the top pane by shrinking the bottom one", () => {
    render(<ThreePaneLayout tree={<p>tree</p>} centreTop={<p>top</p>} centreBottom={<p>bottom</p>} />);
    const separator = screen.getByRole("separator", { name: /resize event history/i });
    const grid = separator.parentElement as HTMLElement;
    const rowHeightPx = () => Number(grid.style.gridTemplateRows.split(" ")[2].replace("px", ""));
    const before = rowHeightPx();

    fireEvent.pointerDown(separator, { clientY: 500, pointerId: 1 });
    fireEvent.pointerMove(separator, { clientY: 550, pointerId: 1 });
    fireEvent.pointerUp(separator, { clientY: 550, pointerId: 1 });

    expect(rowHeightPx()).toBeLessThan(before);
  });

  it("collapses and restores the tree pane via its collapse button", () => {
    render(
      <ThreePaneLayout tree={<p>Device tree content</p>} centreTop={<p>top</p>} centreBottom={<p>bottom</p>} />,
    );
    const collapseButton = screen.getByRole("button", { name: /collapse device tree/i });
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(collapseButton);
    expect(screen.queryByText("Device tree content")).not.toBeInTheDocument();

    const restoreButton = screen.getByRole("button", { name: /expand device tree/i });
    expect(restoreButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(restoreButton);
    expect(screen.getByText("Device tree content")).toBeInTheDocument();
  });

  it("collapses and restores the event history pane via its collapse button", () => {
    render(
      <ThreePaneLayout tree={<p>tree</p>} centreTop={<p>top</p>} centreBottom={<p>Event history content</p>} />,
    );
    const collapseButton = screen.getByRole("button", { name: /collapse event history/i });
    fireEvent.click(collapseButton);
    expect(screen.queryByText("Event history content")).not.toBeInTheDocument();

    const restoreButton = screen.getByRole("button", { name: /expand event history/i });
    fireEvent.click(restoreButton);
    expect(screen.getByText("Event history content")).toBeInTheDocument();
  });
});
