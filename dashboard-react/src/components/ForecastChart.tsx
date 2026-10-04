// Forecast line chart: measured history plus, for a clear trend only, the dashed projection
// the analytics service published (D-18..D-20, D-19a). Hand-written SVG; d3-scale supplies
// scales and ticks only. Every color is a token class resolved through currentColor.
//
// The browser never refits (D-15): the trend line is y(t) = value_at_end +
// slope_per_day * (t - fit_end_ts) / 86400 and the markers sit at the published warn_ts /
// crit_ts. Nothing here derives a slope, a date or a confidence from the history points.

import { useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import type { FitPayload } from "../lib/types";
import type { HistoryPoint } from "../lib/historyClient";

export interface ForecastChartProps {
  points: HistoryPoint[];
  fit: FitPayload | null;
  unit: string;
  nowMs: number;
  rangeDays: number;
  // Leads the aria-label, e.g. "<metric> for <host>".
  label: string;
}

const W = 840;
const PLOT_H = 240;
const M = { left: 48, top: 16, right: 16, bottom: 32 };
const H = PLOT_H + M.top + M.bottom;
const INNER_W = W - M.left - M.right;
const GAP_S = 6 * 3600;
const DAY_MS = 86400000;
const MAX_FORWARD_DAYS = 90;

const NO_TREND_BODY: Record<"stable" | "no_clear_trend", string> = {
  no_clear_trend: "Recent values do not follow a straight line, so no date is predicted.",
  stable: "Values are flat or falling, so no date is predicted.",
};

function formatValue(v: number): string {
  return String(Number(v.toFixed(2)));
}

function formatDate(ms: number, nowMs: number): string {
  const d = new Date(ms);
  const sameYear = d.getFullYear() === new Date(nowMs).getFullYear();
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(d);
}

function formatDateTime(ms: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(ms));
}

function segments(points: HistoryPoint[]): HistoryPoint[][] {
  const out: HistoryPoint[][] = [];
  let current: HistoryPoint[] = [];
  for (const p of points) {
    const prev = current[current.length - 1];
    if (prev && p.t - prev.t > GAP_S) {
      out.push(current);
      current = [];
    }
    current.push(p);
  }
  if (current.length > 0) {
    out.push(current);
  }
  return out;
}

export function ForecastChart({ points, fit, unit, nowMs, rangeDays, label }: ForecastChartProps) {
  const [cursor, setCursor] = useState<number | null>(null);

  const startMs = nowMs - rangeDays * DAY_MS;
  const visible = useMemo(
    () => points.filter((p) => p.t * 1000 >= startMs).sort((a, b) => a.t - b.t),
    [points, startMs],
  );

  // D-19a: trend elements exist only when status is "trending"; the analytics gate already
  // decided that, so the browser does not second-guess it.
  const trending = fit?.status === "trending";

  const lastValue = fit?.last_value ?? (visible.length > 0 ? visible[visible.length - 1].v : null);

  const warn = fit?.warn ?? null;
  const crit = fit?.crit ?? null;
  const warnBreached = warn !== null && lastValue !== null && lastValue >= warn;
  const critBreached = crit !== null && lastValue !== null && lastValue >= crit;

  const warnMarkerMs =
    trending && fit?.warn_ts != null && !warnBreached && fit.warn_ts * 1000 > nowMs
      ? fit.warn_ts * 1000
      : null;
  const critMarkerMs =
    trending && fit?.crit_ts != null && !critBreached && fit.crit_ts * 1000 > nowMs
      ? fit.crit_ts * 1000
      : null;

  const trendReady =
    trending &&
    fit !== null &&
    fit.slope_per_day !== null &&
    fit.value_at_end !== null &&
    fit.fit_end_ts !== null;

  const cap = nowMs + MAX_FORWARD_DAYS * DAY_MS;
  const crossings = [warnMarkerMs, critMarkerMs].filter((v): v is number => v !== null);
  const laterCrossing = crossings.length > 0 ? Math.min(Math.max(...crossings), cap) : null;

  let endMs: number;
  if (trending && laterCrossing !== null) {
    endMs = laterCrossing + (laterCrossing - startMs) * 0.1;
  } else {
    endMs = nowMs + (nowMs - startMs) * 0.1;
  }
  const trendEndMs = trending ? (laterCrossing ?? nowMs + (nowMs - startMs) * 0.1) : null;

  let trendStart: { ms: number; value: number } | null = null;
  let trendEnd: { ms: number; value: number } | null = null;
  if (trendReady && fit && trendEndMs !== null) {
    const fitEndTs = fit.fit_end_ts as number;
    const valueAtEnd = fit.value_at_end as number;
    const slope = fit.slope_per_day as number;
    trendStart = { ms: fitEndTs * 1000, value: valueAtEnd };
    trendEnd = {
      ms: trendEndMs,
      value: valueAtEnd + (slope * (trendEndMs / 1000 - fitEndTs)) / 86400,
    };
  }

  const x = scaleTime()
    .domain([new Date(startMs), new Date(endMs)])
    .range([0, INNER_W]);

  const yValues: number[] = visible.map((p) => p.v);
  if (warn !== null) yValues.push(warn);
  if (crit !== null) yValues.push(crit);
  if (trendEnd) yValues.push(trendEnd.value);
  if (trendStart) yValues.push(trendStart.value);
  const yMin = yValues.length > 0 ? Math.min(...yValues) : 0;
  const yMax = yValues.length > 0 ? Math.max(...yValues) : 1;
  const y = scaleLinear()
    .domain([yMin === yMax ? yMin - 1 : yMin, yMin === yMax ? yMax + 1 : yMax])
    .nice()
    .range([PLOT_H, 0]);
  const yTicks = y.ticks(5);
  const xTicks = x.ticks(6);

  const px = (ms: number) => x(new Date(ms));
  const py = (v: number) => y(v);

  const status = fit?.status ?? null;
  const statusWord =
    status === "trending"
      ? "trending"
      : status === "stable"
        ? "stable"
        : status === "no_clear_trend"
          ? "no clear trend"
          : "no forecast yet";
  const latest = visible.length > 0 ? visible[visible.length - 1].v : lastValue;
  const ariaLabel =
    `${label}: ${latest !== null ? formatValue(latest) : "no data"}${unit}, ${statusWord}` +
    (trending && fit?.crit_ts != null ? `, critical by ${formatDate(fit.crit_ts * 1000, nowMs)}` : "");

  const move = (delta: number) => {
    if (visible.length === 0) return;
    setCursor((c) => {
      const base = c === null ? visible.length - 1 : c;
      return Math.max(0, Math.min(visible.length - 1, base + delta));
    });
  };

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      move(1);
    } else if (event.key === "Escape") {
      setCursor(null);
      (event.currentTarget as SVGSVGElement).blur();
    }
  };

  const onMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || visible.length === 0) return;
    const vx = ((event.clientX - rect.left) / rect.width) * W - M.left;
    let best = 0;
    let bestDist = Infinity;
    visible.forEach((p, i) => {
      const dist = Math.abs(px(p.t * 1000) - vx);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    });
    setCursor(best);
  };

  const cursorPoint = cursor !== null ? (visible[cursor] ?? null) : null;
  const segs = segments(visible);
  const lowConfidence = trending && fit?.confidence === "low";
  const historyDays = fit ? Math.round(fit.history_days) : 0;

  const marker = (ms: number, value: number | null, text: string, tone: string) => {
    if (value === null) return null;
    const cx = px(ms);
    const cy = py(value);
    const flip = cy < 20;
    return (
      <g className={tone} data-testid={text.startsWith("Critical") ? "crit-marker" : "warn-marker"}>
        <circle cx={cx} cy={cy} r={4} fill="currentColor" />
        <text
          x={Math.min(cx, INNER_W - 40)}
          y={flip ? cy + 18 : cy - 10}
          textAnchor="middle"
          fontSize={12}
          fill="currentColor"
        >
          {text}
        </text>
      </g>
    );
  };

  const todayX = px(nowMs);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        {(status === "stable" || status === "no_clear_trend") && (
          <div
            className="pointer-events-none absolute left-0 right-0 top-2 flex justify-center"
            data-testid="status-caption"
          >
            <span className="rounded-pill border border-neutral-300 bg-bg-surface px-2.5 py-1 text-xs font-medium text-fg-secondary">
              {status === "stable" ? "Stable" : "No clear trend"}
            </span>
          </div>
        )}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={ariaLabel}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onMouseMove={onMouseMove}
          onMouseLeave={() => setCursor(null)}
        >
          <g transform={`translate(${M.left},${M.top})`}>
            {yTicks.map((tick, i) => (
              <g key={tick}>
                <line
                  x1={0}
                  x2={INNER_W}
                  y1={py(tick)}
                  y2={py(tick)}
                  stroke="currentColor"
                  strokeOpacity={0.4}
                  className="text-fg-disabled"
                />
                <text
                  x={-6}
                  y={py(tick) + 4}
                  textAnchor="end"
                  fontSize={12}
                  fill="currentColor"
                  className="text-fg-tertiary"
                >
                  {i === yTicks.length - 1 ? `${formatValue(tick)}${unit}` : formatValue(tick)}
                </text>
              </g>
            ))}
            {xTicks.map((tick) => (
              <text
                key={tick.getTime()}
                x={px(tick.getTime())}
                y={PLOT_H + 20}
                textAnchor="middle"
                fontSize={12}
                fill="currentColor"
                className="text-fg-tertiary"
              >
                {formatDate(tick.getTime(), nowMs)}
              </text>
            ))}

            {trending && fit && fit.fit_start_ts !== null && fit.fit_end_ts !== null && (
              <rect
                data-testid="fit-band"
                x={px(fit.fit_start_ts * 1000)}
                y={0}
                width={Math.max(0, px(fit.fit_end_ts * 1000) - px(fit.fit_start_ts * 1000))}
                height={PLOT_H}
                fill="currentColor"
                fillOpacity={0.08}
                className="text-fg-secondary"
              />
            )}

            {warn !== null && (
              <g className="text-warning">
                <line x1={0} x2={INNER_W} y1={py(warn)} y2={py(warn)} stroke="currentColor" strokeWidth={1} />
                <text x={INNER_W} y={py(warn) - 4} textAnchor="end" fontSize={12} fill="currentColor">
                  {`Warn ${formatValue(warn)}${unit}${warnBreached ? " (breached)" : ""}`}
                </text>
              </g>
            )}
            {crit !== null && (
              <g className="text-alert">
                <line x1={0} x2={INNER_W} y1={py(crit)} y2={py(crit)} stroke="currentColor" strokeWidth={1} />
                <text x={INNER_W} y={py(crit) - 4} textAnchor="end" fontSize={12} fill="currentColor">
                  {`Crit ${formatValue(crit)}${unit}${critBreached ? " (breached)" : ""}`}
                </text>
              </g>
            )}

            <g className="text-fg-primary" data-testid="history">
              {segs.map((seg) =>
                seg.length === 1 ? (
                  <circle
                    key={seg[0].t}
                    data-testid="history-segment"
                    cx={px(seg[0].t * 1000)}
                    cy={py(seg[0].v)}
                    r={2}
                    fill="currentColor"
                  />
                ) : (
                  <path
                    key={seg[0].t}
                    data-testid="history-segment"
                    d={seg
                      .map((p, i) => `${i === 0 ? "M" : "L"}${px(p.t * 1000).toFixed(1)} ${py(p.v).toFixed(1)}`)
                      .join(" ")}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                  />
                ),
              )}
            </g>

            {trendStart && trendEnd && (
              <line
                data-testid="trend-line"
                data-start-value={trendStart.value}
                data-end-value={trendEnd.value}
                x1={px(trendStart.ms)}
                y1={py(trendStart.value)}
                x2={px(trendEnd.ms)}
                y2={py(trendEnd.value)}
                stroke="currentColor"
                strokeWidth={2}
                strokeDasharray="6 4"
                opacity={lowConfidence ? 0.5 : 1}
                className="text-fg-secondary"
              />
            )}

            <g className="text-fg-tertiary">
              <line
                x1={todayX}
                x2={todayX}
                y1={0}
                y2={PLOT_H}
                stroke="currentColor"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
              <text x={todayX} y={-4} textAnchor="middle" fontSize={12} fill="currentColor">
                Today
              </text>
            </g>

            {critMarkerMs !== null &&
              marker(critMarkerMs, crit, `Critical ${formatDate(critMarkerMs, nowMs)}`, "text-alert")}
            {warnMarkerMs !== null &&
              marker(warnMarkerMs, warn, `Warning ${formatDate(warnMarkerMs, nowMs)}`, "text-warning")}

            {cursorPoint && (
              <g className="text-fg-primary" data-testid="crosshair">
                <line
                  x1={px(cursorPoint.t * 1000)}
                  x2={px(cursorPoint.t * 1000)}
                  y1={0}
                  y2={PLOT_H}
                  stroke="currentColor"
                  strokeWidth={1}
                />
                <circle cx={px(cursorPoint.t * 1000)} cy={py(cursorPoint.v)} r={3} fill="currentColor" />
              </g>
            )}
          </g>
        </svg>
      </div>

      <div className="min-h-[18px] text-xs text-fg-secondary" data-testid="crosshair-readout" aria-live="polite">
        {cursorPoint ? `${formatDateTime(cursorPoint.t * 1000)} · ${formatValue(cursorPoint.v)}${unit}` : ""}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-secondary">
        <span className="inline-flex items-center gap-1 text-fg-primary">
          <span className="inline-block w-4 border-t-2 border-current" aria-hidden />
          <span className="text-fg-secondary">Measured</span>
        </span>
        {trendStart && (
          <span className="inline-flex items-center gap-1 text-fg-secondary">
            <span className="inline-block w-4 border-t-2 border-dashed border-current" aria-hidden />
            Trend
          </span>
        )}
        {warn !== null && (
          <span className="inline-flex items-center gap-1 text-warning">
            <span className="inline-block w-4 border-t border-current" aria-hidden />
            <span className="text-fg-secondary">Warn</span>
          </span>
        )}
        {crit !== null && (
          <span className="inline-flex items-center gap-1 text-alert">
            <span className="inline-block w-4 border-t border-current" aria-hidden />
            <span className="text-fg-secondary">Crit</span>
          </span>
        )}
        <span className="inline-flex items-center gap-1 text-fg-tertiary">
          <span className="inline-block w-4 border-t border-dotted border-current" aria-hidden />
          <span className="text-fg-secondary">Today</span>
        </span>
      </div>

      {lowConfidence && (
        <p className="text-xs text-fg-secondary">{`${historyDays} days of history, low confidence`}</p>
      )}
      {(status === "stable" || status === "no_clear_trend") && (
        <p className="text-xs text-fg-secondary">{NO_TREND_BODY[status]}</p>
      )}
      {fit && warn === null && crit === null && (
        <p className="text-xs text-fg-secondary">No thresholds defined for this metric.</p>
      )}
    </div>
  );
}
