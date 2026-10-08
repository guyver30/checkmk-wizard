import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForecastDialog } from "./ForecastDialog";
import { MetricHistoryDialog } from "./MetricHistoryDialog";
import { CPU_LOAD_SERIES } from "../lib/historyCharts";
import { useAppStore } from "../store/useAppStore";
import type { DevicePayload, FitPayload } from "../lib/types";

const NOW = Date.UTC(2026, 9, 4, 12, 0, 0);
const NOW_S = NOW / 1000;
const INITIAL_STATE = useAppStore.getState();

function utilFit(overrides: Partial<FitPayload> = {}): FitPayload {
  return {
    service: "CPU utilization",
    metric: "util",
    unit: "%",
    status: "no_clear_trend",
    slope_per_day: null,
    value_at_end: null,
    fit_start_ts: null,
    fit_end_ts: null,
    r2: null,
    history_days: 14,
    confidence: null,
    last_value: 40,
    warn: 85,
    crit: 95,
    warn_ts: null,
    crit_ts: null,
    warn_date: null,
    crit_date: null,
    days_to_warn: null,
    days_to_crit: null,
    ...overrides,
  };
}

function seed(device: Partial<DevicePayload> | null, fits: FitPayload[]) {
  act(() => {
    useAppStore.setState({
      devices: device ? ({ web1: device } as unknown as Record<string, DevicePayload>) : {},
      forecasts: {
        web1: { host: "web1", generated_at: new Date(NOW - 5 * 60000).toISOString(), fits },
      },
    });
  });
}

function rows(n: number, v: number) {
  return Array.from({ length: n }, (_, i) => ({ t: NOW_S - (n - i) * 3600, v }));
}

// Different rows per series, chosen from the typed param_m binding.
function fetchByMetric(empty: string[] = []) {
  return vi.fn(async (url: string) => {
    const q = new URL(url, "http://x").searchParams;
    const m = q.get("param_m") ?? "";
    const v = m === "load1" ? 0.12 : m === "load5" ? 0.3 : m === "load15" ? 0.25 : 40;
    const data = empty.includes(m) ? [] : rows(48, v);
    return new Response(JSON.stringify({ data }), { status: 200 });
  }) as unknown as typeof fetch;
}

function calls(fn: typeof fetch) {
  return (fn as unknown as ReturnType<typeof vi.fn>).mock.calls as [string][];
}

function renderLoad(fetchFn: typeof fetch, onClose = vi.fn()) {
  render(
    <MetricHistoryDialog
      host="web1"
      title="CPU load"
      series={CPU_LOAD_SERIES}
      unit=""
      warn={12}
      crit={20}
      onClose={onClose}
      nowMs={NOW}
      fetchFn={fetchFn}
    />,
  );
  return onClose;
}

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

describe("ForecastDialog for a history-only metric", () => {
  function renderUtil(fetchFn: typeof fetch) {
    render(
      <ForecastDialog
        host="web1"
        service="CPU utilization"
        metric="util"
        onClose={vi.fn()}
        nowMs={NOW}
        fetchFn={fetchFn}
      />,
    );
  }

  it("shows the history chart with Checkmk levels and no forecast wording", async () => {
    seed({ cpu_warn: 80, cpu_crit: 90 }, [utilFit()]);
    renderUtil(fetchByMetric());
    expect(screen.getByRole("heading", { name: "web1 · CPU utilization util" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Warn 80%")).toBeInTheDocument());
    expect(screen.getByText("Crit 90%")).toBeInTheDocument();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).not.toMatch(
      /Confidence|No forecast yet|No clear trend|Stable|has not computed a forecast|As of|Stale/,
    );
    for (const id of ["trend-line", "fit-band", "crit-marker", "warn-marker", "status-caption"]) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
  });

  it("falls back to the fit's levels when the device has none", async () => {
    seed({ cpu_warn: null, cpu_crit: null }, [utilFit()]);
    renderUtil(fetchByMetric());
    await waitFor(() => expect(screen.getByText("Warn 85%")).toBeInTheDocument());
    expect(screen.getByText("Crit 95%")).toBeInTheDocument();
  });

  it("still charts with no fit and no device", async () => {
    seed(null, []);
    renderUtil(fetchByMetric());
    await waitFor(() => expect(screen.getAllByTestId("history-segment").length).toBeGreaterThan(0));
    expect(screen.getByText("No levels defined for this metric.")).toBeInTheDocument();
  });

  it("does not use the history view for other metrics", async () => {
    seed({}, [utilFit({ service: "Filesystem /", metric: "fs_used_percent" })]);
    render(
      <ForecastDialog
        host="web1"
        service="Filesystem /"
        metric="fs_used_percent"
        onClose={vi.fn()}
        nowMs={NOW}
        fetchFn={fetchByMetric()}
      />,
    );
    expect(screen.getByText("No clear trend")).toBeInTheDocument();
  });
});

describe("MetricHistoryDialog", () => {
  it("fetches the three load series and draws three lines with levels", async () => {
    const fn = fetchByMetric();
    renderLoad(fn);
    expect(screen.getByTestId("chart-skeleton")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId("history-series")).toHaveLength(3));
    expect(calls(fn).map(([url]) => new URL(url, "http://x").searchParams.get("param_m")).sort()).toEqual([
      "load1",
      "load15",
      "load5",
    ]);
    expect(screen.getByText("Warn 12")).toBeInTheDocument();
    expect(screen.getByText("Crit 20")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "web1 · CPU load" })).toBeInTheDocument();
  });

  it("shows a warning without forecast wording when a series fails", async () => {
    let n = 0;
    const fn = vi.fn(async () => {
      n += 1;
      if (n === 2) return new Response("no", { status: 500 });
      return new Response(JSON.stringify({ data: rows(5, 1) }), { status: 200 });
    }) as unknown as typeof fetch;
    renderLoad(fn);
    await waitFor(() => expect(screen.getByText("Couldn't load history")).toBeInTheDocument());
    expect(screen.getByRole("dialog").textContent).not.toMatch(/forecast/i);
  });

  it("shows the empty message when every series is empty", async () => {
    renderLoad(fetchByMetric(["load1", "load5", "load15"]));
    await waitFor(() => expect(screen.getByText("No history in this range.")).toBeInTheDocument());
    expect(screen.queryByTestId("history-series")).toBeNull();
  });

  it("still renders the chart when only some series are empty", async () => {
    renderLoad(fetchByMetric(["load5"]));
    await waitFor(() => expect(screen.getAllByTestId("history-series")).toHaveLength(3));
    expect(screen.queryByText("No history in this range.")).toBeNull();
  });

  it("refetches every series when the range changes", async () => {
    const fn = fetchByMetric();
    renderLoad(fn);
    await waitFor(() => expect(screen.getAllByTestId("history-series")).toHaveLength(3));
    expect(calls(fn).every(([url]) => new URL(url, "http://x").searchParams.get("param_d") === "14")).toBe(true);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "30" } });
    await waitFor(() => expect(calls(fn).length).toBe(6));
    const second = calls(fn).slice(3);
    expect(second.every(([url]) => new URL(url, "http://x").searchParams.get("param_d") === "30")).toBe(true);
  });

  it("focuses Close and closes on Escape, scrim click and Close", () => {
    const onClose = renderLoad(fetchByMetric());
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("forecast-scrim"));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

