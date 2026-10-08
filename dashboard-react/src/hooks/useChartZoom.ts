// Zoom and pan state for the time axis of the SVG charts (ForecastChart, HistoryChart):
// wheel at the pointer, drag, +/-/0 keys, Shift+Arrow pan. The pure domain maths lives in
// lib/chartZoom.ts; this hook owns the state, the native wheel listener and the drag.
//
// Zoom state is keyed to the full domain, so it resets when the range or metric changes and
// when the dialog is reopened. Plain Arrow keys are not handled here: each chart keeps its own
// crosshair stepping, and handleZoomKey returns false for anything it does not consume.

import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { CHART } from "../lib/chartCommon";
import {
  clampDomain,
  isFullDomain,
  panBy,
  revealTime,
  zoomAt,
  type Domain,
} from "../lib/chartZoom";

export interface ChartZoom {
  svgRef: React.RefObject<SVGSVGElement | null>;
  view: Domain;
  zoomed: boolean;
  dragging: boolean;
  applyZoom: (fn: (current: Domain, full: Domain) => Domain) => void;
  zoomBy: (anchorMs: number, factor: number) => void;
  reset: () => void;
  reveal: (ms: number) => void;
  handleZoomKey: (event: KeyboardEvent<SVGSVGElement>, anchorMs: number) => boolean;
  onMouseDown: (event: MouseEvent<SVGSVGElement>) => void;
  dragMove: (event: MouseEvent<SVGSVGElement>) => boolean;
  endDrag: () => void;
}

export function useChartZoom(full: Domain): ChartZoom {
  const [zoom, setZoom] = useState<{ key: string; domain: Domain } | null>(null);
  const [dragging, setDragging] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ x: number; view: Domain } | null>(null);
  const zoomCtx = useRef<{ full: Domain; key: string; view: Domain }>({
    full: [0, 1],
    key: "",
    view: [0, 1],
  });

  const fullKey = `${full[0]}|${full[1]}`;
  const view: Domain = zoom && zoom.key === fullKey ? clampDomain(zoom.domain, full) : full;
  const zoomed = !isFullDomain(view, full);
  zoomCtx.current = { full, key: fullKey, view };

  // Applies a domain transform to the latest view. Reads the ref so the native wheel
  // listener (bound once) and the render-time handlers share one code path.
  const applyZoom = (fn: (current: Domain, fullDomain: Domain) => Domain) => {
    setZoom((prev) => {
      const ctx = zoomCtx.current;
      const current = prev && prev.key === ctx.key ? clampDomain(prev.domain, ctx.full) : ctx.full;
      const next = fn(current, ctx.full);
      return isFullDomain(next, ctx.full) ? null : { key: ctx.key, domain: next };
    });
  };

  // React's onWheel is passive and cannot preventDefault, so the wheel listener is native.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      if (event.deltaY === 0) return;
      const rect = svg.getBoundingClientRect();
      const frac =
        rect.width === 0
          ? 0.5
          : Math.min(
              1,
              Math.max(0, ((((event.clientX - rect.left) / rect.width) * CHART.W) - CHART.M.left) / CHART.INNER_W),
            );
      const factor = event.deltaY < 0 ? 0.8 : 1.25;
      applyZoom((cur, f) => zoomAt(cur, cur[0] + frac * (cur[1] - cur[0]), factor, f));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
    // applyZoom only touches state setters and a ref, so binding once is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const zoomBy = (anchorMs: number, factor: number) => {
    applyZoom((cur, f) => zoomAt(cur, anchorMs, factor, f));
  };
  const reset = () => setZoom(null);
  const reveal = (ms: number) => {
    applyZoom((cur, f) => revealTime(cur, ms, f));
  };

  const handleZoomKey = (event: KeyboardEvent<SVGSVGElement>, anchorMs: number): boolean => {
    if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && event.shiftKey) {
      event.preventDefault();
      const dir = event.key === "ArrowLeft" ? -1 : 1;
      applyZoom((cur, f) => panBy(cur, dir * 0.2 * (cur[1] - cur[0]), f));
      return true;
    }
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomBy(anchorMs, 0.5);
      return true;
    }
    if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoomBy(anchorMs, 2);
      return true;
    }
    if (event.key === "0") {
      event.preventDefault();
      reset();
      return true;
    }
    return false;
  };

  const endDrag = () => {
    dragRef.current = null;
    setDragging(false);
  };

  const onMouseDown = (event: MouseEvent<SVGSVGElement>) => {
    if (event.button !== 0 || !zoomed) return;
    dragRef.current = { x: event.clientX, view };
    setDragging(true);
  };

  // True when a drag consumed the move (the chart then skips its crosshair update).
  const dragMove = (event: MouseEvent<SVGSVGElement>): boolean => {
    const drag = dragRef.current;
    if (!drag) return false;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return true;
    const startView = drag.view;
    const deltaMs =
      ((((event.clientX - drag.x) / rect.width) * CHART.W) / CHART.INNER_W) * (startView[1] - startView[0]);
    applyZoom((_cur, f) => panBy(startView, -deltaMs, f));
    return true;
  };

  return { svgRef, view, zoomed, dragging, applyZoom, zoomBy, reset, reveal, handleZoomKey, onMouseDown, dragMove, endDrag };
}
