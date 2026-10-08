// History line chart for metrics that are charted for history and Checkmk levels only (CPU
// utilization and CPU load, quick 261008-kr3): one or more measured series plus flat warn/crit
// level lines. It never reads a fit, never projects, and has no Today line because the time
// axis ends now. Hand-written SVG; d3-scale supplies scales and ticks only.
//
// Zoom and pan are the shared useChartZoom hook and ChartZoomToolbar, so the interaction is
// identical to ForecastChart (wheel at the pointer, drag, +/-/0 keys, Shift+Arrow, toolbar,
// double click). Plain ArrowLeft/ArrowRight step the crosshair through the times at which any
// series has a point.
//
// Series styling (a design choice, all token classes): the first series is solid primary at
// 2 px, the second secondary at 1.5 px, the third tertiary at 1.5 px dashed "4 3", so the
// three load averages stay distinguishable without relying on colour alone.

import { useId, useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { useChartZoom } from "../hooks/useChartZoom";
import {
  CHART,
  DAY_MS,
  formatDate,
  formatDateTime,
  formatValue,
  segments,
  unionTimes,
  valueAt,
} from "../lib/chartCommon";
import type { Domain } from "../lib/chartZoom";
import type { HistoryPoint } from "../lib/historyClient";
import { ChartZoomToolbar } from "./ChartZoomToolbar";

export interface HistoryChartSeries {
  label: string;
  points: HistoryPoint[];
}

export interface HistoryChartProps {
  series: HistoryChartSeries[];
  warn: number | null;
  crit: number | null;
  unit: string;
  nowMs: number;
  rangeDays: number;
  // Leads the aria-label, e.g. "CPU load for <host>".
  label: string;
}

const { W, PLOT_H, M, H, INNER_W } = CHART;

const SERIES_STYLE = [
  { className: "text-fg-primary", strokeWidth: 2, dash: undefined },
  { className: "text-fg-secondary", strokeWidth: 1.5, dash: undefined },
  { className: "text-fg-tertiary", strokeWidth: 1.5, dash: "4 3" },
] as const;

function styleFor(index: number) {
  return SERIES_STYLE[Math.min(index, SERIES_STYLE.length - 1)];
}

export function HistoryChart({ series, warn, crit, unit, nowMs, rangeDays, label }: HistoryChartProps) {
  const [cursor, setCursor] = useState<number | null>(null);
  const clipId = `clip-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;

  const startMs = nowMs - rangeDays * DAY_MS;
  const visible = useMemo(
    () =>
      series.map((s) => ({
        label: s.label,
        points: s.points.filter((p) => p.t * 1000 >= startMs).sort((a, b) => a.t - b.t),
      })),
    [series, startMs],
  );
  const times = useMemo(() => unionTimes(visible.map((s) => s.points)), [visible]);
  const multi = visible.length > 1;

  const full: Domain = [startMs, nowMs];
  const zoomState = useChartZoom(full);
  const { svgRef, view, zoomed, dragging } = zoomState;
  const inView = (ms: number) => ms >= view[0] && ms <= view[1];

  const x = scaleTime()
    .domain([new Date(view[0]), new Date(view[1])])
    .range([0, INNER_W]);

  const firstSeries = visible[0]?.points ?? [];
  const lastValue = firstSeries.length > 0 ? firstSeries[firstSeries.length - 1].v : null;
  const warnBreached = warn !== null && lastValue !== null && lastValue >= warn;
  const critBreached = crit !== null && lastValue !== null && lastValue >= crit;

  // Full view: every value plus both levels, so the levels are visible (the point of the
  // chart). Zoomed: rescale to what is in the window; a level is drawn only if it falls
  // inside the resulting y domain.
  const yValues: number[] = [];
  for (const s of visible) {
    for (const p of s.points) {
      if (!zoomed || inView(p.t * 1000)) yValues.push(p.v);
    }
  }
  if (!zoomed) {
    if (warn !== null) yValues.push(warn);
    if (crit !== null) yValues.push(crit);
  }
  const yMin = yValues.length > 0 ? Math.min(...yValues) : 0;
  const yMax = yValues.length > 0 ? Math.max(...yValues) : 1;
  const y = scaleLinear()
    .domain([yMin === yMax ? yMin - 1 : yMin, yMin === yMax ? yMax + 1 : yMax])
    .nice()
    .range([PLOT_H, 0]);
  const yTicks = y.ticks(5);
  const xTicks = x.ticks(6);
  const [yLo, yHi] = y.domain();
  const levelInDomain = (v: number) => v >= yLo && v <= yHi;
  const longWindow = view[1] - view[0] > 2 * DAY_MS;

  const px = (ms: number) => x(new Date(ms));
  const py = (v: number) => y(v);

  const latestParts = visible
    .filter((s) => s.points.length > 0)
    .map((s) => ({ label: s.label, v: s.points[s.points.length - 1].v }));
  const latestText =
    latestParts.length === 0
      ? "no data"
      : multi
        ? latestParts.map((p) => `${p.label} ${formatValue(p.v)}${unit}`).join(", ")
        : `${formatValue(latestParts[0].v)}${unit}`;
  const ariaLabel =
    `${label}: ${latestText}` +
    (zoomed ? `, showing ${formatDate(view[0], nowMs)} to ${formatDate(view[1], nowMs)}` : "");

  const cursorT = cursor !== null ? (times[cursor] ?? null) : null;
  const zoomAnchor = () => (cursorT !== null ? cursorT * 1000 : (view[0] + view[1]) / 2);

  const move = (delta: number) => {
    if (times.length === 0) return;
    let base = cursor;
    if (base === null) {
      // First step starts from the last time inside the window, not the last overall.
      base = times.length - 1;
      for (let i = times.length - 1; i >= 0; i--) {
        if (inView(times[i] * 1000)) {
          base = i;
          break;
        }
      }
    }
    const next = Math.max(0, Math.min(times.length - 1, base + delta));
    setCursor(next);
    zoomState.reveal(times[next] * 1000);
  };

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (zoomState.handleZoomKey(event, zoomAnchor())) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      move(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === "Escape") {
      setCursor(null);
      (event.currentTarget as SVGSVGElement).blur();
    }
  };

  const onMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    if (zoomState.dragMove(event)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || times.length === 0) return;
    const vx = ((event.clientX - rect.left) / rect.width) * W - M.left;
    let best = -1;
    let bestDist = Infinity;
    times.forEach((t, i) => {
      if (!inView(t * 1000)) return;
      const dist = Math.abs(px(t * 1000) - vx);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    });
    if (best >= 0) setCursor(best);
  };

  const readout =
    cursorT !== null
      ? `${formatDateTime(cursorT * 1000)} · ` +
        visible
          .map((s) => {
            const v = valueAt(s.points, cursorT);
            return v === null ? null : multi ? `${s.label} ${formatValue(v)}${unit}` : `${formatValue(v)}${unit}`;
          })
          .filter((part): part is string => part !== null)
          .join(" · ")
      : "";

  // Points inside the window plus the nearest one on each side, so lines run to the edge.
  const windowSegments = (points: HistoryPoint[]) => {
    let firstIn = points.findIndex((p) => p.t * 1000 >= view[0]);
    if (firstIn < 0) firstIn = points.length;
    let lastIn = -1;
    points.forEach((p, i) => {
      if (p.t * 1000 <= view[1]) lastIn = i;
    });
    return segments(points.slice(Math.max(0, firstIn - 1), lastIn + 2));
  };

  return (
    <div className="flex flex-col gap-2">
      <ChartZoomToolbar
        view={view}
        full={full}
        zoomed={zoomed}
        onZoomIn={() => zoomState.zoomBy(zoomAnchor(), 0.5)}
        onZoomOut={() => zoomState.zoomBy(zoomAnchor(), 2)}
        onReset={zoomState.reset}
      />
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          style={zoomed ? { cursor: dragging ? "grabbing" : "grab" } : undefined}
          role="img"
          aria-label={ariaLabel}
          data-zoomed={zoomed ? "true" : "false"}
          data-zoom-start={view[0]}
          data-zoom-end={view[1]}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onMouseDown={zoomState.onMouseDown}
          onMouseUp={zoomState.endDrag}
          onDoubleClick={zoomState.reset}
          onMouseMove={onMouseMove}
          onMouseLeave={() => {
            zoomState.endDrag();
            setCursor(null);
          }}
        >
          <defs>
            <clipPath id={clipId}>
              <rect x={0} y={-M.top} width={INNER_W} height={PLOT_H + M.top} />
            </clipPath>
          </defs>
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
                {longWindow ? formatDate(tick.getTime(), nowMs) : formatDateTime(tick.getTime())}
              </text>
            ))}

            <g clipPath={`url(#${clipId})`}>
              {warn !== null && levelInDomain(warn) && (
                <g className="text-warning">
                  <line x1={0} x2={INNER_W} y1={py(warn)} y2={py(warn)} stroke="currentColor" strokeWidth={1} />
                  <text x={INNER_W} y={py(warn) - 4} textAnchor="end" fontSize={12} fill="currentColor">
                    {`Warn ${formatValue(warn)}${unit}${warnBreached ? " (breached)" : ""}`}
                  </text>
                </g>
              )}
              {crit !== null && levelInDomain(crit) && (
                <g className="text-alert">
                  <line x1={0} x2={INNER_W} y1={py(crit)} y2={py(crit)} stroke="currentColor" strokeWidth={1} />
                  <text x={INNER_W} y={py(crit) - 4} textAnchor="end" fontSize={12} fill="currentColor">
                    {`Crit ${formatValue(crit)}${unit}${critBreached ? " (breached)" : ""}`}
                  </text>
                </g>
              )}

              {visible.map((s, index) => {
                const style = styleFor(index);
                return (
                  <g
                    key={s.label}
                    className={style.className}
                    data-testid="history-series"
                    data-series={s.label}
                  >
                    {windowSegments(s.points).map((seg) =>
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
                          strokeWidth={style.strokeWidth}
                          strokeDasharray={style.dash}
                        />
                      ),
                    )}
                  </g>
                );
              })}

              {cursorT !== null && (
                <g className="text-fg-primary" data-testid="crosshair">
                  <line
                    x1={px(cursorT * 1000)}
                    x2={px(cursorT * 1000)}
                    y1={0}
                    y2={PLOT_H}
                    stroke="currentColor"
                    strokeWidth={1}
                  />
                  {visible.map((s) => {
                    const v = valueAt(s.points, cursorT);
                    return v === null ? null : (
                      <circle key={s.label} cx={px(cursorT * 1000)} cy={py(v)} r={3} fill="currentColor" />
                    );
                  })}
                </g>
              )}
            </g>
          </g>
        </svg>
      </div>

      <div className="min-h-[18px] text-xs text-fg-secondary" data-testid="crosshair-readout" aria-live="polite">
        {readout}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-secondary">
        {visible.map((s, index) => {
          const style = styleFor(index);
          return (
            <span key={s.label} className={`inline-flex items-center gap-1 ${style.className}`}>
              <span
                className={`inline-block w-4 border-t-2 border-current ${style.dash ? "border-dashed" : ""}`}
                aria-hidden
              />
              <span className="text-fg-secondary">{multi ? s.label : "Measured"}</span>
            </span>
          );
        })}
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
      </div>

      {warn === null && crit === null && (
        <p className="text-xs text-fg-secondary">No levels defined for this metric.</p>
      )}
    </div>
  );
}
