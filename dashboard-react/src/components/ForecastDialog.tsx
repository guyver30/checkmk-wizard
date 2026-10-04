// Modal forecast chart for one (host, service, metric): measured hourly history from
// /ch-api/ (historyClient) plus the fit the analytics service published on the retained
// forecast topic. Any entry point opens it with just those three values; the dialog finds the
// fit itself. A metric with no fit still charts its history (D-18).
//
// The design system has no Dialog component, so this is a fixed scrim plus a role="dialog"
// panel, like the admin confirm dialog.

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { Badge, Button, Message, Select, Tooltip } from "kone-design-system";
import { fetchHourlyHistory, type HistoryDays, type HistoryResult } from "../lib/historyClient";
import { isStaleGeneratedAt } from "../lib/forecast";
import type { ForecastConfidence } from "../lib/types";
import { useAppStore } from "../store/useAppStore";
import { ForecastChart } from "./ForecastChart";

export interface ForecastDialogProps {
  host: string;
  service: string;
  metric: string;
  onClose: () => void;
  nowMs?: number;
  fetchFn?: typeof fetch;
}

const RANGE_OPTIONS = [
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

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

export function ForecastDialog({ host, service, metric, onClose, nowMs, fetchFn }: ForecastDialogProps) {
  const forecast = useAppStore((s) => s.forecasts[host]);
  const fit = useMemo(
    () => forecast?.fits.find((f) => f.service === service && f.metric === metric) ?? null,
    [forecast, service, metric],
  );
  const [now] = useState(() => nowMs ?? Date.now());
  const [range, setRange] = useState<HistoryDays>(() => defaultRange(fit?.fit_start_ts ?? null, fit?.fit_end_ts ?? null));
  const [history, setHistory] = useState<HistoryState>({ status: "loading" });
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

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

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const trapTab = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !panelRef.current) return;
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), select:not([disabled]), [tabindex="0"]',
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      data-testid="forecast-scrim"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="forecast-dialog-title"
        className="max-h-[90vh] w-full max-w-[880px] overflow-auto rounded-md bg-bg-surface p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapTab}
      >
        <div className="flex items-start gap-4 rounded-md bg-bg-subtle p-4">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h2 id="forecast-dialog-title" className="truncate text-xl font-semibold text-fg-primary">
              {`${host} · ${service} ${metric}`}
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              {headerBadge}
              {fit && <span className="text-xs text-fg-secondary">{`${historyDays} days of history`}</span>}
            </div>
            {!fit && (
              <p className="text-xs text-fg-secondary">
                The analytics service has not computed a forecast for this metric. It runs every 15 minutes.
              </p>
            )}
          </div>
          <div className="w-32 shrink-0">
            <Select
              id="forecast-range"
              label="Range"
              options={RANGE_OPTIONS}
              value={String(range)}
              onChange={(event: ChangeEvent<HTMLSelectElement>) => setRange(Number(event.target.value) as HistoryDays)}
            />
          </div>
          <Button ref={closeRef} variant="neutral" size="sm" onClick={onClose} aria-label="Close">
            Close
          </Button>
        </div>

        <div className="mt-4">
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
        </div>

        {hasGenerated && (
          <div className="mt-2 text-xs" role="status">
            {stale ? (
              <Tooltip content="The analytics service has not published recently." position="top">
                <span className="text-warning">{`Stale, last update ${hhmm(generatedMs)}`}</span>
              </Tooltip>
            ) : (
              <span className="text-fg-tertiary">{`As of ${hhmm(generatedMs)}`}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
