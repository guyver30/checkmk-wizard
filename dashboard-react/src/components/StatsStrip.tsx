// DASH-01's counts-by-state strip, built on kone-design-system's own StatTile. Always shows
// the OK tile (even at zero) so a healthy fleet still gives a positive "0 down" signal; every
// other state renders only when its count is greater than zero, keeping the strip a thin row
// (D-25) rather than growing to all eight tiles on a healthy fleet.

import { StatTile } from "kone-design-system";
import type { StateCounts } from "../store/selectors";

const DANGER_STATES = new Set(["DOWN", "CRIT"]);

// Display order: worst-first among the non-OK states, OK always first.
const DISPLAY_ORDER: (keyof StateCounts)[] = ["OK", "DOWN", "CRIT", "UNREACH", "WARN", "UNKNOWN", "STALE", "PEND"];

export interface StatsStripProps {
  counts: StateCounts;
}

export function StatsStrip({ counts }: StatsStripProps) {
  const tiles = DISPLAY_ORDER.filter((state) => state === "OK" || counts[state] > 0);

  return (
    <div className="flex flex-wrap gap-2" role="status" aria-label="Fleet state summary">
      {tiles.map((state) => (
        <StatTile
          key={state}
          label={state}
          value={counts[state]}
          tone={DANGER_STATES.has(state) ? "danger" : "neutral"}
        />
      ))}
    </div>
  );
}
