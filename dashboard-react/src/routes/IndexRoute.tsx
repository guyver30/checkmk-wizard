import { useCallback, useState } from "react";
import { useShallow } from "zustand/shallow";
import { MapPlaceholder } from "../components/MapPlaceholder";
import { StatsStrip } from "../components/StatsStrip";
import { ThreePaneLayout } from "../components/ThreePaneLayout";
import { makeSelectStateCounts } from "../store/selectors";
import { useAppStore } from "../store/useAppStore";

export function IndexRoute() {
  // A stable selector (memoized on nowMs) subscribed through useAppStore, not a one-off
  // `makeSelectStateCounts(nowMs)(useAppStore.getState())` read -- the latter would bypass
  // Zustand's subscription entirely and never re-render this route on a device update.
  // nowMs is captured once via useState's lazy initialiser rather than read fresh on every
  // render, since a fresh `Date.now()` per render would recreate the selector every render.
  // `useShallow` compares the selector's output by value, not by reference -- `selectCounts`
  // allocates a brand-new counts object on every call (selectors.ts), so without it
  // useSyncExternalStore would treat every store notification as "changed" and loop forever.
  const [nowMs] = useState(() => Date.now());
  const selectCounts = useCallback(makeSelectStateCounts(nowMs), [nowMs]);
  const counts = useAppStore(useShallow(selectCounts));

  return (
    <ThreePaneLayout
      tree={
        // Plan 08 fills the device tree in here.
        <p className="p-3 text-sm text-fg-tertiary">Device tree</p>
      }
      centreTop={
        // D-25: the stats strip sits ABOVE the map placeholder, content-sized, with the
        // placeholder taking the remaining height -- both are always visible together.
        <div className="flex h-full flex-col gap-2 p-3">
          <StatsStrip counts={counts} />
          <div className="min-h-0 flex-1">
            <MapPlaceholder />
          </div>
        </div>
      }
      centreBottom={
        // Plan 10 fills the event history in here.
        <p className="p-3 text-sm text-fg-tertiary">Event history</p>
      }
    />
  );
}
