import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MapPlaceholder } from "./MapPlaceholder";
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

  it("renders all three named pane regions, including the map placeholder", () => {
    render(
      <ThreePaneLayout
        tree={<p>Device tree content</p>}
        centreTop={<MapPlaceholder />}
        centreBottom={<p>Event history content</p>}
      />,
    );
    expect(screen.getByText("Device tree content")).toBeInTheDocument();
    expect(screen.getByText("Topology map — Phase 13")).toBeInTheDocument();
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
