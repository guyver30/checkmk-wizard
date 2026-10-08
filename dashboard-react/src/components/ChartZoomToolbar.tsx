import { Button } from "kone-design-system";
import { isMinSpan, type Domain } from "../lib/chartZoom";

// The zoom toolbar shared by ForecastChart and HistoryChart.
export interface ChartZoomToolbarProps {
  view: Domain;
  full: Domain;
  zoomed: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
}

export function ChartZoomToolbar({ view, full, zoomed, onZoomIn, onZoomOut, onReset }: ChartZoomToolbarProps) {
  return (
    <div className="flex justify-end gap-2" role="toolbar" aria-label="Chart zoom">
      <Button variant="neutral" size="sm" aria-label="Zoom in" disabled={isMinSpan(view, full)} onClick={onZoomIn}>
        +
      </Button>
      <Button variant="neutral" size="sm" aria-label="Zoom out" disabled={!zoomed} onClick={onZoomOut}>
        −
      </Button>
      <Button variant="neutral" size="sm" aria-label="Reset zoom" disabled={!zoomed} onClick={onReset}>
        Reset
      </Button>
    </div>
  );
}
