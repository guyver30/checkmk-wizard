import { useCallback, useMemo, useState } from "react";
import { useShallow } from "zustand/shallow";
import { MapPlaceholder } from "../components/MapPlaceholder";
import { StatsStrip } from "../components/StatsStrip";
import { ThreePaneLayout } from "../components/ThreePaneLayout";
import { Tree } from "../components/Tree";
import { buildTree } from "../lib/treeModel";
import { makeSelectStateCounts } from "../store/selectors";
import { useAppStore } from "../store/useAppStore";

export function IndexRoute() {
  // A stable selector (memoized on nowMs) subscribed through useAppStore, not a one-off
  // `makeSelectStateCounts(nowMs)(useAppStore.getState())` read -- the latter would bypass
  // Zustand's subscription entirely and never re-render this route on a device update.
  // `makeSelectStateCounts` is the same factory selectors.ts's clock-agnostic `selectStateCounts`
  // is built from (`selectStateCounts` itself pins nowMs at import time, which this component
  // must not do). nowMs is captured once via useState's lazy initialiser rather than read fresh
  // on every render, since a fresh `Date.now()` per render would recreate the selector every
  // render. `useShallow` compares the selector's output by value, not by reference --
  // `selectCounts` allocates a brand-new counts object on every call (selectors.ts), so without
  // it useSyncExternalStore would treat every store notification as "changed" and loop forever.
  const [nowMs] = useState(() => Date.now());
  const selectCounts = useCallback(makeSelectStateCounts(nowMs), [nowMs]);
  const counts = useAppStore(useShallow(selectCounts));

  // Grouping mode is hardcoded to "type" in this plan (plan 09 replaces it with the
  // <select> and the severity-ordered checkbox). Open-group state is lifted here, not into
  // Tree/TreeNode, so a device-status message re-rendering this route never resets it --
  // openKeys is a plain Set the store update has no reason to touch.
  const devices = useAppStore((s) => s.devices);
  const groups = useMemo(() => buildTree(devices, "type"), [devices]);
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());
  const onToggleGroup = useCallback((key: string) => {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  return (
    <ThreePaneLayout
      tree={<Tree groups={groups} openKeys={openKeys} onToggle={onToggleGroup} />}
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
