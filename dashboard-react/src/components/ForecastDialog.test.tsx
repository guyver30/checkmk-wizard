import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForecastDialog, defaultRange } from "./ForecastDialog";
import { useAppStore } from "../store/useAppStore";
import type { FitPayload } from "../lib/types";

const NOW = Date.UTC(2026, 9, 4, 12, 0, 0);
const NOW_S = NOW / 1000;
const DAY = 86400;
const INITIAL_STATE = useAppStore.getState();

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
    warn_date: null,
    crit_date: null,
    days_to_warn: 20,
    days_to_crit: 30,
    ...overrides,
  };
}

function setForecast(fits: FitPayload[], generatedAt = new Date(NOW - 5 * 60000).toISOString()) {
  act(() => {
    useAppStore.setState({ forecasts: { web1: { host: "web1", generated_at: generatedAt, fits } } });
  });
}

function rows(n: number) {
  return Array.from({ length: n }, (_, i) => ({ t: NOW_S - (n - i) * 3600, v: 50 + i * 0.01 }));
}

function fetchOk(n = 48) {
  return vi.fn(async () => new Response(JSON.stringify({ data: rows(n) }), { status: 200 })) as unknown as typeof fetch;
}

function renderDialog(fetchFn: typeof fetch, onClose = vi.fn()) {
  render(
    <ForecastDialog
      host="web1"
      service="Filesystem /"
      metric="fs_used_percent"
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

describe("defaultRange", () => {
  it("rounds fit window plus 7 days up to 14, 30 or 90", () => {
    expect(defaultRange(null, null)).toBe(14);
    expect(defaultRange(0, 3 * DAY)).toBe(14);
    expect(defaultRange(0, 10 * DAY)).toBe(30);
    expect(defaultRange(0, 40 * DAY)).toBe(90);
  });
});

describe("ForecastDialog", () => {
  it("renders an accessible dialog with title, focused close button and the chart", async () => {
    setForecast([fit()]);
    renderDialog(fetchOk());
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("heading", { name: "web1 · Filesystem / fs_used_percent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await waitFor(() => expect(screen.getByTestId("trend-line")).toBeInTheDocument());
    expect(screen.getByText("Confidence: high")).toBeInTheDocument();
    expect(screen.getByText("14 days of history")).toBeInTheDocument();
    expect(screen.getByText(/^As of \d\d:\d\d$/)).toBeInTheDocument();
  });

  it("shows a skeleton and no level lines while loading", () => {
    setForecast([fit()]);
    renderDialog(vi.fn(() => new Promise<Response>(() => {})) as unknown as typeof fetch);
    expect(screen.getByTestId("chart-skeleton")).toBeInTheDocument();
    expect(screen.queryByText(/^Warn /)).toBeNull();
  });

  it("closes on Escape and on scrim click but not on panel click", () => {
    setForecast([fit()]);
    const onClose = renderDialog(fetchOk());
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("forecast-scrim"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("defaults the range from the fit window and refetches on change", async () => {
    setForecast([fit({ fit_start_ts: NOW_S - 10 * DAY })]);
    const fn = fetchOk();
    renderDialog(fn);
    await waitFor(() => expect(screen.getByTestId("trend-line")).toBeInTheDocument());
    const mock = fn as unknown as ReturnType<typeof vi.fn>;
    expect(new URL(mock.mock.calls[0][0] as string, "http://x").searchParams.get("param_d")).toBe("30");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "90" } });
    await waitFor(() => expect(mock.mock.calls.length).toBe(2));
    expect(new URL(mock.mock.calls[1][0] as string, "http://x").searchParams.get("param_d")).toBe("90");
  });

  it("shows the history error while still rendering the header", async () => {
    setForecast([fit()]);
    renderDialog(vi.fn(async () => new Response("x", { status: 500 })) as unknown as typeof fetch);
    expect(await screen.findByText("Couldn't load history")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /web1/ })).toBeInTheDocument();
    expect(screen.getByText("Confidence: high")).toBeInTheDocument();
  });

  it("shows the empty state when there are no rows", async () => {
    setForecast([fit()]);
    renderDialog(fetchOk(0));
    expect(await screen.findByText("No history in this range.")).toBeInTheDocument();
  });

  it("shows 'No forecast yet' and history only when the metric has no fit", async () => {
    setForecast([fit({ metric: "other" })]);
    renderDialog(fetchOk());
    expect(screen.getByText("No forecast yet")).toBeInTheDocument();
    expect(
      screen.getByText(/has not computed a forecast for this metric/),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId("history-segment").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("trend-line")).toBeNull();
  });

  it("shows the stale treatment past 45 minutes", () => {
    setForecast([fit()], new Date(NOW - 60 * 60000).toISOString());
    renderDialog(fetchOk());
    expect(screen.getByText(/^Stale, last update \d\d:\d\d$/)).toBeInTheDocument();
  });

  it("D-19a: a stable fit has no trend element in the dialog", async () => {
    setForecast([fit({ status: "stable" })]);
    renderDialog(fetchOk());
    await waitFor(() => expect(screen.getAllByTestId("history-segment").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("trend-line")).toBeNull();
    expect(screen.getAllByText("Stable").length).toBeGreaterThan(0);
  });
});
