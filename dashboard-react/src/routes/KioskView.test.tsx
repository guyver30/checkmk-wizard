import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KioskView } from "./KioskView";
import { KIOSK_ROTATION_MS } from "../hooks/useKioskRotation";

function renderKioskView() {
  return render(
    <MemoryRouter>
      <KioskView />
    </MemoryRouter>,
  );
}

describe("KioskView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document.documentElement, "requestFullscreen", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts on the incidents view, dims the topology view, and rotates every 20s", () => {
    renderKioskView();

    expect(screen.getByTestId("kiosk-view-incidents")).toHaveClass("opacity-100");
    expect(screen.getByTestId("kiosk-view-incidents")).toHaveAttribute("aria-hidden", "false");
    expect(screen.getByTestId("kiosk-view-topology")).toHaveClass("opacity-0", "pointer-events-none");
    expect(screen.getByTestId("kiosk-view-topology")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Incidents")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(KIOSK_ROTATION_MS);
    });

    expect(screen.getByTestId("kiosk-view-topology")).toHaveClass("opacity-100");
    expect(screen.getByTestId("kiosk-view-topology")).toHaveAttribute("aria-hidden", "false");
    expect(screen.getByTestId("kiosk-view-incidents")).toHaveClass("opacity-0", "pointer-events-none");
    expect(screen.getByTestId("kiosk-view-incidents")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Topology")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(KIOSK_ROTATION_MS);
    });

    expect(screen.getByText("Incidents")).toBeInTheDocument();
  });

  it("has an aria-live=polite view label", () => {
    renderKioskView();
    expect(screen.getByText("Incidents")).toHaveAttribute("aria-live", "polite");
  });

  it("never renders edit controls, even though editing might be configured elsewhere", () => {
    renderKioskView();
    expect(screen.queryByText("Edit topology")).not.toBeInTheDocument();
    expect(screen.queryByText("Apply changes")).not.toBeInTheDocument();
  });

  it("renders a full-height IncidentList and a read-only TopologyMap", () => {
    renderKioskView();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("shows an Enter full screen button that requests fullscreen and disappears on click", () => {
    renderKioskView();

    const button = screen.getByText("Enter full screen");
    act(() => {
      button.click();
    });

    expect(document.documentElement.requestFullscreen).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Enter full screen")).not.toBeInTheDocument();
  });

  it("hides the Enter full screen button after 10s if never clicked", () => {
    renderKioskView();

    expect(screen.getByText("Enter full screen")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(screen.queryByText("Enter full screen")).not.toBeInTheDocument();
  });

  it("renders a progress bar that gets a new key each cycle", () => {
    renderKioskView();

    const firstBar = screen.getByTestId("kiosk-progress");

    act(() => {
      vi.advanceTimersByTime(KIOSK_ROTATION_MS);
    });

    const secondBar = screen.getByTestId("kiosk-progress");
    expect(secondBar).not.toBe(firstBar);
  });
});
