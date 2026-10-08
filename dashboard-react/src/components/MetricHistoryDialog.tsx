// Modal history chart for metrics that are charted for history and Checkmk levels only (CPU
// utilization and CPU load, quick 261008-kr3): nothing forecast-related is shown. Series come
// from /ch-api/ (historyClient, one query per series); warn/crit come from the caller.
//
// MetricHistoryDialog is generic over a list of series; HistoryOnlyMetricDialog is the single
// (host, service, metric) entry that ForecastDialog dispatches history-only metrics to.

import { useEffect, useState } from "react";
import { Message } from "kone-design-system";
import {
  fetchHistorySeries,
  type HistoryDays,
  type HistoryPoint,
  type HistorySeriesSpec,
} from "../lib/historyClient";
import { CPU_UTIL_METRIC, historyLevels } from "../lib/historyCharts";
import { useAppStore } from "../store/useAppStore";
import { ChartDialogFrame } from "./ChartDialogFrame";
import { HistoryChart } from "./HistoryChart";

export interface MetricHistoryDialogProps {
  host: string;
  title: string;
  series: ReadonlyArray<HistorySeriesSpec & { label: string }>;
  unit: string;
  warn: number | null;
  crit: number | null;
  onClose: () => void;
  nowMs?: number;
  fetchFn?: typeof fetch;
}

type HistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ok"; series: HistoryPoint[][] };

export function MetricHistoryDialog({
  host,
  title,
  series,
  unit,
  warn,
  crit,
  onClose,
  nowMs,
  fetchFn,
}: MetricHistoryDialogProps) {
  const [now] = useState(() => nowMs ?? Date.now());
  const [range, setRange] = useState<HistoryDays>(14);
  const [history, setHistory] = useState<HistoryState>({ status: "loading" });
  const seriesKey = series.map((s) => `${s.service}|${s.metric}`).join(",");

  useEffect(() => {
    let cancelled = false;
    setHistory({ status: "loading" });
    const specs = series.map((s) => ({ service: s.service, metric: s.metric }));
    void fetchHistorySeries(host, specs, range, fetchFn).then((result) => {
      if (cancelled) return;
      setHistory(result.ok ? { status: "ok", series: result.series } : { status: "error" });
    });
    return () => {
      cancelled = true;
    };
    // series is identified by seriesKey; the array identity changes every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host, seriesKey, range, fetchFn]);

  const allEmpty = history.status === "ok" && history.series.every((points) => points.length === 0);

  return (
    <ChartDialogFrame title={`${host} · ${title}`} range={range} onRangeChange={setRange} onClose={onClose}>
      {history.status === "loading" && (
        <div className="h-[240px] rounded-md bg-bg-subtle" data-testid="chart-skeleton" />
      )}
      {history.status === "error" && (
        <Message
          status="warning"
          shadow={false}
          title="Couldn't load history"
          description="The history store did not answer. Try again in a moment."
        />
      )}
      {allEmpty && <p className="text-sm text-fg-secondary">No history in this range.</p>}
      {history.status === "ok" && !allEmpty && (
        <HistoryChart
          series={series.map((s, i) => ({ label: s.label, points: history.series[i] ?? [] }))}
          warn={warn}
          crit={crit}
          unit={unit}
          nowMs={now}
          rangeDays={range}
          label={`${title} for ${host}`}
        />
      )}
    </ChartDialogFrame>
  );
}

export interface HistoryOnlyMetricDialogProps {
  host: string;
  service: string;
  metric: string;
  onClose: () => void;
  nowMs?: number;
  fetchFn?: typeof fetch;
}

export function HistoryOnlyMetricDialog({
  host,
  service,
  metric,
  onClose,
  nowMs,
  fetchFn,
}: HistoryOnlyMetricDialogProps) {
  const device = useAppStore((s) => s.devices[host]);
  const forecast = useAppStore((s) => s.forecasts[host]);
  const fit = forecast?.fits.find((f) => f.service === service && f.metric === metric) ?? null;
  const levels = historyLevels(metric, device, fit);
  const unit = fit?.unit ?? (metric === CPU_UTIL_METRIC ? "%" : "");

  return (
    <MetricHistoryDialog
      host={host}
      title={`${service} ${metric}`}
      series={[{ service, metric, label: metric }]}
      unit={unit}
      warn={levels.warn}
      crit={levels.crit}
      onClose={onClose}
      nowMs={nowMs}
      fetchFn={fetchFn}
    />
  );
}
