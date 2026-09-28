// DASH-01's counts-by-state strip. Since 2026-09-28 it sits in the header next to the Overview
// link as compact badges (operator request: free the space above the map), rather than as a row
// of StatTiles on the dashboard. Always shows OK (even at zero) so a healthy fleet still gives a
// positive signal; every other state renders only when its count is greater than zero.

import { useCallback } from "react";
import { useShallow } from "zustand/shallow";
import { Badge, type BadgeColor } from "kone-design-system";
import { useNowTick } from "../hooks/useNowTick";
import { makeSelectStateCounts, type StateCounts } from "../store/selectors";
import { useAppStore } from "../store/useAppStore";

// Display order: OK first, then worst-first among the non-OK states.
const DISPLAY_ORDER: (keyof StateCounts)[] = ["OK", "DOWN", "CRIT", "UNREACH", "WARN", "UNKNOWN", "STALE", "PEND"];

const STATE_COLOR: Record<keyof StateCounts, BadgeColor> = {
  OK: "success",
  DOWN: "danger",
  CRIT: "danger",
  UNREACH: "warning",
  WARN: "warning",
  UNKNOWN: "neutral",
  STALE: "neutral",
  PEND: "neutral",
};

export interface StatsStripProps {
  counts: StateCounts;
}

export function StatsStrip({ counts }: StatsStripProps) {
  const states = DISPLAY_ORDER.filter((state) => state === "OK" || counts[state] > 0);

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="status" aria-label="Fleet state summary">
      {states.map((state) => (
        <span key={state} data-state={state}>
          <Badge variant="soft" color={STATE_COLOR[state]}>
            {state} {counts[state]}
          </Badge>
        </span>
      ))}
    </div>
  );
}

// The header's live instance. useNowTick drives staleness (D-34), and the memoized selector plus
// useShallow keep Zustand from looping on the freshly allocated counts object (see selectors.ts).
export function HeaderStats() {
  const nowMs = useNowTick();
  const selectCounts = useCallback(makeSelectStateCounts(nowMs), [nowMs]);
  const counts = useAppStore(useShallow(selectCounts));
  return <StatsStrip counts={counts} />;
}
