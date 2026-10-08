// Modal forecast chart for one (host, service, metric): measured hourly history from
// /ch-api/ (historyClient) plus the fit the analytics service published on the retained
// forecast topic. Any entry point opens it with just those three values; the dialog finds the
// fit itself. A metric with no fit still charts its history (D-18).
//
// The dialog shell is ChartDialogFrame. Metrics that are history-only (utilization, load) are
// dispatched to MetricHistoryDialog instead and show no forecast.

import { useEffect, useMemo, useState } from "react";
import { Badge, Message, Tooltip } from "kone-design-system";
import { fetchHourlyHistory, type HistoryDays, type HistoryResult } from "../lib/historyClient";
import { isStaleGeneratedAt } from "../lib/forecast";
import type { ForecastConfidence } from "../lib/types";
import { useAppStore } from "../store/useAppStore";
import { isHistoryOnlyMetric } from "../lib/historyCharts";
import { ChartDialogFrame } from "./ChartDialogFrame";
import { ForecastChart } from "./ForecastChart";
import { HistoryOnlyMetricDialog } from "./MetricHistoryDialog";

export interface ForecastDialogProps {
  host: string;
  service: string;
  metric: string;
  onClose: () => void;
  nowMs?: number;
  fetchFn?: typeof fetch;
}

const CONFIDENCE_BADGE: Record<ForecastConfidence, "solid" | "soft" | "outline"> = {
  high: "solid",
  medium: "soft",
  low: "outline",
};

// Fit window plus 7 days, rounded up to the nearest option; 14 when there is no fit window.
export function defaultRange(fitStartTs: number | null, fitEndTs: number | null): HistoryDays {
  if (fitStartTs === null || fitEndTs === null) {
    return 14;
  }
  const days = (fitEndTs - fitStartTs) / 86400 + 7;
  if (days <= 14) return 14;
  if (days <= 30) return 30;
  return 90;
}

function hhmm(ms: number): string {
  const d = new Date(ms);
  const pad = (v: number) => String(v).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

type HistoryState = { status: "loading" } | { status: "error" } | { status: "ok"; points: Extract<HistoryResult, { ok: true }>["points"] };

function ForecastView({ host, service, metric, onClose, nowMs, fetchFn }: ForecastDialogProps) {
  const forecast = useAppStore((s) => s.forecasts[host]);
  const fit = useMemo(
    () => forecast?.fits.find((f) => f.service === service && f.metric === metric) ?? null,
    [forecast, service, metric],
  );
  const [now] = useState(() => nowMs ?? Date.now());
  const [range, setRange] = useState<HistoryDays>(() => defaultRange(fit?.fit_start_ts ?? null, fit?.fit_end_ts ?? null));
  const [history, setHistory] = useState<HistoryState>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setHistory({ status: "loading" });
    void fetchHourlyHistory(host, service, metric, range, fetchFn).then((result) => {
      if (cancelled) return;
      setHistory(result.ok ? { status: "ok", points: result.points } : { status: "error" });
    });
    return () => {
      cancelled = true;
    };
  }, [host, service, metric, range, fetchFn]);

  const generatedMs = forecast ? Date.parse(forecast.generated_at) : NaN;
  const hasGenerated = Number.isFinite(generatedMs);
  const stale = hasGenerated && isStaleGeneratedAt(generatedMs, now);
  const historyDays = fit ? Math.round(fit.history_days) : 0;

  let headerBadge;
  if (!fit) {
    headerBadge = <Badge color="neutral" variant="outline">No forecast yet</Badge>;
  } else if (fit.status === "trending") {
    headerBadge = (
      <Badge color="neutral" variant={CONFIDENCE_BADGE[fit.confidence ?? "low"]}>
        {`Confidence: ${fit.confidence ?? "low"}`}
      </Badge>
    );
  } else {
    headerBadge = (
      <Badge color="neutral" variant="outline">
        {fit.status === "stable" ? "Stable" : "No clear trend"}
      </Badge>
    );
  }

  return (
    <ChartDialogFrame
      title={`${host} · ${service} ${metric}`}
      headerExtra={
        <>
          <div className="flex flex-wrap items-center gap-2">
            {headerBadge}
            {fit && <span className="text-xs text-fg-secondary">{`${historyDays} days of history`}</span>}
          </div>
          {!fit && (
            <p className="text-xs text-fg-secondary">
              The analytics service has not computed a forecast for this metric. It runs every 15 minutes.
            </p>
          )}
        </>
      }
      range={range}
      onRangeChange={setRange}
      onClose={onClose}
      footer={
        hasGenerated ? (
          <div className="mt-2 text-xs" role="status">
            {stale ? (
              <Tooltip content="The analytics service has not published recently." position="top">
                <span className="text-warning">{`Stale, last update ${hhmm(generatedMs)}`}</span>
              </Tooltip>
            ) : (
              <span className="text-fg-tertiary">{`As of ${hhmm(generatedMs)}`}</span>
            )}
          </div>
        ) : undefined
      }
    >
      {history.status === "loading" && (
        <div className="h-[240px] rounded-md bg-bg-subtle" data-testid="chart-skeleton" />
      )}
      {history.status === "error" && (
        <Message
          status="warning"
          shadow={false}
          title="Couldn't load history"
          description="The history store did not answer. The forecast numbers above are still current. Try again in a moment."
        />
      )}
      {history.status === "ok" && history.points.length === 0 && (
        <p className="text-sm text-fg-secondary">No history in this range.</p>
      )}
      {history.status === "ok" && history.points.length > 0 && (
        <ForecastChart
          points={history.points}
          fit={fit}
          unit={fit?.unit ?? ""}
          nowMs={now}
          rangeDays={range}
          label={`${metric} for ${host}`}
        />
      )}
    </ChartDialogFrame>
  );
}

// Per quick 261008-kr3 operator decision, CPU utilization (and load) are history-only, so every
// existing entry point (host details Trends and need rows, NeedRow in the Needs pane) lands on
// the history view without each caller knowing. Analytics still publishes the util fit; this
// dispatcher is where the dashboard ignores it.
export function ForecastDialog(props: ForecastDialogProps) {
  if (isHistoryOnlyMetric(props.metric)) {
    return (
      <HistoryOnlyMetricDialog
        host={props.host}
        service={props.service}
        metric={props.metric}
        onClose={props.onClose}
        nowMs={props.nowMs}
        fetchFn={props.fetchFn}
      />
    );
  }
  return <ForecastView {...props} />;
}
