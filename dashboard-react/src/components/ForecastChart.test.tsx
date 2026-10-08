import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ForecastChart } from "./ForecastChart";
import type { FitPayload } from "../lib/types";

const NOW = Date.UTC(2026, 9, 4, 12, 0, 0);
const NOW_S = NOW / 1000;
const DAY = 86400;

function history(days: number, valueAt: (i: number) => number = (i) => 50 + i * 0.01) {
  const out = [];
  const n = days * 24;
  for (let i = 0; i < n; i++) {
    out.push({ t: NOW_S - (n - i) * 3600, v: valueAt(i) });
  }
  return out;
}

function fit(overrides: Partial<FitPayload> = {}): FitPayload {
  return {
    service: "Filesystem /",
    metric: "fs_used_percent",
    unit: "%",
    status: "trending",
    slope_per_day: 1,
    value_at_end: 60,
    fit_start_ts: NOW_S - 10 * DAY,
    fit_end_ts: NOW_S - 3600,
    r2: 0.97,
    history_days: 14,
    confidence: "high",
    last_value: 60,
    warn: 80,
    crit: 90,
    warn_ts: NOW_S + 20 * DAY,
    crit_ts: NOW_S + 30 * DAY,
    warn_date: "2026-10-24",
    crit_date: "2026-11-03",
    days_to_warn: 20,
    days_to_crit: 30,
    ...overrides,
  };
}

function renderChart(f: FitPayload | null, extra: { points?: ReturnType<typeof history> } = {}) {
  return render(
    <ForecastChart
      points={extra.points ?? history(14)}
      fit={f}
      unit="%"
      nowMs={NOW}
      rangeDays={14}
      label="fs_used_percent for web1"
    />,
  );
}

describe("ForecastChart", () => {
  it("draws the dashed trend, fit band and both markers for a clear trend", () => {
    renderChart(fit());
    const trend = screen.getByTestId("trend-line");
    expect(trend.getAttribute("stroke-dasharray")).toBe("6 4");
    expect(screen.getByTestId("fit-band")).toBeInTheDocument();
    expect(screen.getByTestId("crit-marker").textContent).toMatch(/^Critical \d+ \w+/);
    expect(screen.getByTestId("warn-marker").textContent).toMatch(/^Warning /);
  });

  it("projects the trend from the published parameters without refitting", () => {
    const f = fit({ slope_per_day: 0.5, value_at_end: 60 });
    renderChart(f);
    const trend = screen.getByTestId("trend-line");
    // The trend ends at the later crossing (crit_ts).
    const tEnd = f.crit_ts as number;
    const expected = 60 + (0.5 * (tEnd - (f.fit_end_ts as number))) / 86400;
    expect(Number(trend.getAttribute("data-start-value"))).toBe(60);
    expect(Number(trend.getAttribute("data-end-value"))).toBeCloseTo(expected, 6);
  });

  it("draws only the crit marker when warn_date is null", () => {
    renderChart(fit({ warn_ts: null, warn_date: null, days_to_warn: null }));
    expect(screen.getByTestId("crit-marker")).toBeInTheDocument();
    expect(screen.queryByTestId("warn-marker")).toBeNull();
  });

  it("lowers opacity and captions history_days (not the fit window) for low confidence", () => {
    renderChart(fit({ confidence: "low", history_days: 9, fit_start_ts: NOW_S - 3 * DAY }));
    expect(screen.getByTestId("trend-line").getAttribute("opacity")).toBe("0.5");
    expect(screen.getByText("9 days of history, low confidence")).toBeInTheDocument();
  });

  it("uses full opacity for medium and high confidence", () => {
    renderChart(fit({ confidence: "medium" }));
    expect(screen.getByTestId("trend-line").getAttribute("opacity")).toBe("1");
    expect(screen.queryByText(/low confidence/)).toBeNull();
  });

  it.each([
    ["no_clear_trend", "No clear trend", "Recent values do not follow a straight line, so no date is predicted."],
    ["stable", "Stable", "Values are flat or falling, so no date is predicted."],
  ] as const)("D-19a: %s draws no trend elements", (status, word, body) => {
    renderChart(
      fit({
        status,
        slope_per_day: null,
        value_at_end: null,
        fit_start_ts: null,
        fit_end_ts: null,
        crit_ts: null,
        warn_ts: null,
      }),
    );
    expect(screen.queryByTestId("trend-line")).toBeNull();
    expect(screen.queryByTestId("fit-band")).toBeNull();
    expect(screen.queryByTestId("crit-marker")).toBeNull();
    expect(screen.queryByTestId("warn-marker")).toBeNull();
    expect(screen.getByTestId("status-caption")).toHaveTextContent(word);
    expect(screen.getByText(body)).toBeInTheDocument();
  });

  it("D-19a: a non-trending status draws no trend even if slope fields are present", () => {
    renderChart(fit({ status: "no_clear_trend" }));
    expect(screen.queryByTestId("trend-line")).toBeNull();
    expect(screen.queryByTestId("fit-band")).toBeNull();
    expect(screen.queryByTestId("crit-marker")).toBeNull();
  });

  it("draws history only when there is no fit", () => {
    renderChart(null);
    expect(screen.getAllByTestId("history-segment").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^Warn /)).toBeNull();
    expect(screen.queryByText(/^Crit /)).toBeNull();
    expect(screen.queryByTestId("trend-line")).toBeNull();
  });

  it("shows the no-threshold caption when warn and crit are both null", () => {
    renderChart(fit({ status: "stable", warn: null, crit: null }));
    expect(screen.getByText("No thresholds defined for this metric.")).toBeInTheDocument();
    expect(screen.queryByText(/^Warn /)).toBeNull();
  });

  it("omits a marker and labels the level breached when already past it", () => {
    renderChart(fit({ last_value: 85, warn: 80, warn_ts: NOW_S - DAY }));
    expect(screen.queryByTestId("warn-marker")).toBeNull();
    expect(screen.getByText("Warn 80% (breached)")).toBeInTheDocument();
    expect(screen.getByTestId("crit-marker")).toBeInTheDocument();
  });

  it("breaks the history line at gaps longer than 6 hours", () => {
    const pts = [
      { t: NOW_S - 10 * 3600, v: 1 },
      { t: NOW_S - 9 * 3600, v: 2 },
      { t: NOW_S - 2 * 3600, v: 3 },
      { t: NOW_S - 1 * 3600, v: 4 },
    ];
    renderChart(null, { points: pts });
    expect(screen.getAllByTestId("history-segment")).toHaveLength(2);
  });

  it("labels the svg and steps a keyboard crosshair", () => {
    renderChart(fit());
    const svg = screen.getByRole("img");
    expect(svg.getAttribute("aria-label")).toMatch(
      /^fs_used_percent for web1: .*%, trending, critical by \d+ \w+/,
    );
    fireEvent.keyDown(svg, { key: "ArrowLeft" });
    expect(screen.getByTestId("crosshair")).toBeInTheDocument();
    expect(screen.getByTestId("crosshair-readout").textContent).toMatch(/ · .*%$/);
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(screen.queryByTestId("crosshair")).toBeNull();
  });

  describe("zoom and pan", () => {
    const zoomed = () => screen.getByRole("img").getAttribute("data-zoomed");
    const zoomIn = () => fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    it("has a zoom toolbar with zoom out and reset disabled at full view", () => {
      renderChart(fit());
      expect(screen.getByRole("toolbar", { name: "Chart zoom" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Reset zoom" })).toBeDisabled();
      expect(zoomed()).toBe("false");
      zoomIn();
      expect(zoomed()).toBe("true");
      expect(screen.getByRole("button", { name: "Zoom out" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Reset zoom" })).toBeEnabled();
    });

    it("hides markers outside the window and restores them on reset", () => {
      renderChart(fit());
      zoomIn();
      zoomIn();
      expect(screen.queryByTestId("crit-marker")).toBeNull();
      expect(screen.queryByTestId("warn-marker")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));
      expect(screen.getByTestId("crit-marker")).toBeInTheDocument();
      expect(screen.getByTestId("warn-marker")).toBeInTheDocument();
      expect(zoomed()).toBe("false");
    });

    it("zooms with the wheel and prevents the default scroll", () => {
      renderChart(fit());
      const svg = screen.getByRole("img");
      const notPrevented = fireEvent.wheel(svg, { deltaY: -100 });
      expect(notPrevented).toBe(false);
      expect(zoomed()).toBe("true");
    });

    it("zooming out with the wheel at full view stays at full", () => {
      renderChart(fit());
      fireEvent.wheel(screen.getByRole("img"), { deltaY: 100 });
      expect(zoomed()).toBe("false");
    });

    it("resets on double click", () => {
      renderChart(fit());
      zoomIn();
      fireEvent.doubleClick(screen.getByRole("img"));
      expect(zoomed()).toBe("false");
    });

    it("supports + - 0 keys", () => {
      renderChart(fit());
      const svg = screen.getByRole("img");
      fireEvent.keyDown(svg, { key: "+" });
      expect(zoomed()).toBe("true");
      fireEvent.keyDown(svg, { key: "-" });
      expect(zoomed()).toBe("false");
      fireEvent.keyDown(svg, { key: "=" });
      fireEvent.keyDown(svg, { key: "0" });
      expect(zoomed()).toBe("false");
    });

    it("Shift+Arrow pans without creating a crosshair", () => {
      renderChart(fit());
      const svg = screen.getByRole("img");
      fireEvent.keyDown(svg, { key: "+" });
      fireEvent.keyDown(svg, { key: "+" });
      const before = svg.getAttribute("data-zoom-start");
      fireEvent.keyDown(svg, { key: "ArrowLeft", shiftKey: true });
      expect(svg.getAttribute("data-zoom-start")).not.toBe(before);
      expect(screen.queryByTestId("crosshair")).toBeNull();
    });

    it("clips plotted layers with a clipPath", () => {
      const { container } = renderChart(fit());
      const group = container.querySelector("g[clip-path]");
      expect(group).not.toBeNull();
      const id = /url\(#(.+)\)/.exec(group?.getAttribute("clip-path") ?? "")?.[1];
      expect(id).toBeTruthy();
      expect(container.querySelector(`clipPath[id="${id}"]`)).not.toBeNull();
    });

    it("resets the zoom when the range changes", () => {
      const props = { points: history(14), fit: fit(), unit: "%", nowMs: NOW, label: "x" };
      const { rerender } = render(<ForecastChart {...props} rangeDays={14} />);
      zoomIn();
      expect(zoomed()).toBe("true");
      rerender(<ForecastChart {...props} rangeDays={7} />);
      expect(zoomed()).toBe("false");
    });
  });
});
