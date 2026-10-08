import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HistoryChart } from "./HistoryChart";

const NOW = Date.UTC(2026, 9, 4, 12, 0, 0);
const NOW_S = NOW / 1000;

function history(days: number, valueAt: (i: number) => number = () => 42) {
  const out = [];
  const n = days * 24;
  for (let i = 0; i < n; i++) {
    out.push({ t: NOW_S - (n - i) * 3600, v: valueAt(i) });
  }
  return out;
}

function renderUtil(overrides: Partial<React.ComponentProps<typeof HistoryChart>> = {}) {
  return render(
    <HistoryChart
      series={[{ label: "util", points: history(14) }]}
      warn={80}
      crit={90}
      unit="%"
      nowMs={NOW}
      rangeDays={14}
      label="util for web1"
      {...overrides}
    />,
  );
}

function renderLoad(overrides: Partial<React.ComponentProps<typeof HistoryChart>> = {}) {
  return render(
    <HistoryChart
      series={[
        { label: "1 min", points: history(14, () => 0.12) },
        { label: "5 min", points: history(14, () => 0.3) },
        { label: "15 min", points: history(14, () => 0.25) },
      ]}
      warn={12}
      crit={20}
      unit=""
      nowMs={NOW}
      rangeDays={14}
      label="CPU load for web1"
      {...overrides}
    />,
  );
}

describe("HistoryChart single series", () => {
  it("draws the measured line and the level lines and nothing forecast", () => {
    const { container } = renderUtil();
    expect(screen.getAllByTestId("history-segment").length).toBeGreaterThan(0);
    expect(screen.getByText("Warn 80%")).toBeInTheDocument();
    expect(screen.getByText("Crit 90%")).toBeInTheDocument();
    for (const id of ["trend-line", "fit-band", "crit-marker", "warn-marker", "status-caption"]) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(container.textContent).not.toMatch(/Today|Stable|No clear trend|confidence|no date is predicted/i);
    expect(screen.getByText("Measured")).toBeInTheDocument();
  });

  it("labels a level breached when the latest value is at or above it", () => {
    renderUtil({ series: [{ label: "util", points: history(14, () => 85) }] });
    expect(screen.getByText("Warn 80% (breached)")).toBeInTheDocument();
    expect(screen.getByText("Crit 90%")).toBeInTheDocument();
  });

  it("shows a caption and draws no level line when both levels are null", () => {
    renderUtil({ warn: null, crit: null });
    expect(screen.getByText("No levels defined for this metric.")).toBeInTheDocument();
    expect(screen.queryByText(/^Warn /)).toBeNull();
    expect(screen.queryByText(/^Crit /)).toBeNull();
  });

  it("puts the latest value in the aria-label and the window when zoomed", () => {
    renderUtil();
    const svg = screen.getByRole("img");
    expect(svg.getAttribute("aria-label")).toBe("util for web1: 42%");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("img").getAttribute("aria-label")).toMatch(/^util for web1: 42%, showing .+ to .+/);
  });

  it("ends the x domain at now", () => {
    renderUtil();
    expect(Number(screen.getByRole("img").getAttribute("data-zoom-end"))).toBe(NOW);
  });

  it("steps a crosshair with ArrowLeft and clears it with Escape", () => {
    renderUtil();
    const svg = screen.getByRole("img");
    fireEvent.keyDown(svg, { key: "ArrowLeft" });
    expect(screen.getByTestId("crosshair")).toBeInTheDocument();
    expect(screen.getByTestId("crosshair-readout").textContent).toMatch(/ · 42%$/);
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(screen.queryByTestId("crosshair")).toBeNull();
  });
});

describe("HistoryChart three series", () => {
  it("renders one group per series, a legend entry each, and unit-less level labels", () => {
    renderLoad();
    const groups = screen.getAllByTestId("history-series");
    expect(groups.map((g) => g.getAttribute("data-series"))).toEqual(["1 min", "5 min", "15 min"]);
    expect(screen.getByText("Warn 12")).toBeInTheDocument();
    expect(screen.getByText("Crit 20")).toBeInTheDocument();
    for (const label of ["1 min", "5 min", "15 min", "Warn", "Crit"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.queryByText("Measured")).toBeNull();
    // The third series is dashed.
    const dashed = within(groups[2]).getAllByTestId("history-segment")[0];
    expect(dashed.getAttribute("stroke-dasharray")).toBe("4 3");
  });

  it("reads the latest value of every series in the aria-label", () => {
    renderLoad();
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "CPU load for web1: 1 min 0.12, 5 min 0.3, 15 min 0.25",
    );
  });

  it("shows one crosshair dot per series and a joined readout", () => {
    renderLoad();
    fireEvent.keyDown(screen.getByRole("img"), { key: "ArrowLeft" });
    expect(screen.getByTestId("crosshair").querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByTestId("crosshair-readout").textContent).toMatch(
      / · 1 min 0.12 · 5 min 0.3 · 15 min 0.25$/,
    );
  });

  it("omits a series without a value at the crosshair time", () => {
    renderLoad({
      series: [
        { label: "1 min", points: history(14, () => 0.12) },
        { label: "5 min", points: [{ t: NOW_S - 100 * 3600, v: 0.3 }] },
        { label: "15 min", points: history(14, () => 0.25) },
      ],
    });
    fireEvent.keyDown(screen.getByRole("img"), { key: "ArrowLeft" });
    expect(screen.getByTestId("crosshair").querySelectorAll("circle")).toHaveLength(2);
    expect(screen.getByTestId("crosshair-readout").textContent).not.toMatch(/· 5 min/);
  });
});

describe("HistoryChart zoom", () => {
  it("has a toolbar with zoom out and reset disabled at full view", () => {
    renderUtil();
    expect(screen.getByRole("toolbar", { name: "Chart zoom" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset zoom" })).toBeDisabled();
    expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("false");
  });

  it("zooms in from the toolbar and resets on double click", () => {
    renderUtil();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("true");
    fireEvent.doubleClick(screen.getByRole("img"));
    expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("false");
  });

  it("zooms with the wheel and prevents the default scroll", () => {
    renderUtil();
    const svg = screen.getByRole("img");
    const notPrevented = fireEvent.wheel(svg, { deltaY: -100 });
    expect(notPrevented).toBe(false);
    expect(svg.getAttribute("data-zoomed")).toBe("true");
  });

  it("handles + - 0 keys and Shift+Arrow pan without a crosshair", () => {
    renderUtil();
    const svg = screen.getByRole("img");
    fireEvent.keyDown(svg, { key: "+" });
    expect(svg.getAttribute("data-zoomed")).toBe("true");
    const before = svg.getAttribute("data-zoom-start");
    fireEvent.keyDown(svg, { key: "ArrowLeft", shiftKey: true });
    expect(svg.getAttribute("data-zoom-start")).not.toBe(before);
    expect(screen.queryByTestId("crosshair")).toBeNull();
    fireEvent.keyDown(svg, { key: "-" });
    fireEvent.keyDown(svg, { key: "0" });
    expect(svg.getAttribute("data-zoomed")).toBe("false");
  });

  it("clips the plotted layers", () => {
    const { container } = renderUtil();
    const group = container.querySelector("g[clip-path]");
    expect(group).not.toBeNull();
    const id = /url\(#(.+)\)/.exec(group?.getAttribute("clip-path") ?? "")?.[1];
    expect(container.querySelector(`clipPath[id="${id}"]`)).not.toBeNull();
  });

  it("resets the zoom when the range changes", () => {
    const { rerender } = renderUtil();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("true");
    rerender(
      <HistoryChart
        series={[{ label: "util", points: history(30) }]}
        warn={80}
        crit={90}
        unit="%"
        nowMs={NOW}
        rangeDays={30}
        label="util for web1"
      />,
    );
    expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("false");
  });
});
