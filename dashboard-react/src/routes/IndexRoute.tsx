import { useCallback, useMemo, useState } from "react";
import { useShallow } from "zustand/shallow";
import { EventHistory } from "../components/EventHistory";
import { GroupingControls } from "../components/GroupingControls";
import { MapPlaceholder } from "../components/MapPlaceholder";
import { StatsStrip } from "../components/StatsStrip";
import { ThreePaneLayout } from "../components/ThreePaneLayout";
import { Tree } from "../components/Tree";
import { useGroupingPrefs } from "../hooks/useGroupingPrefs";
import { useNowTick } from "../hooks/useNowTick";
import { buildTree } from "../lib/treeModel";
import type { GroupingMode } from "../lib/types";
import { makeSelectStateCounts } from "../store/selectors";
import { useAppStore } from "../store/useAppStore";

export function IndexRoute() {
  // useNowTick is the app's single periodic clock (D-34): it drives every time-derived
  // surface on this route so staleness becomes visible even when the poller goes silent and
  // no new MQTT message ever arrives. A stable selector (memoized on nowMs) is subscribed
  // through useAppStore, not a one-off `makeSelectStateCounts(nowMs)(useAppStore.getState())`
  // read -- the latter would bypass Zustand's subscription entirely and never re-render this
  // route on a device update. `makeSelectStateCounts` is the same factory selectors.ts's
  // clock-agnostic `selectStateCounts` is built from (`selectStateCounts` itself pins nowMs
  // at import time, which this component must not do). `useShallow` compares the selector's
  // output by value, not by reference -- `selectCounts` allocates a brand-new counts object
  // on every call (selectors.ts), so without it useSyncExternalStore would treat every store
  // notification as "changed" and loop forever.
  const nowMs = useNowTick();
  const selectCounts = useCallback(makeSelectStateCounts(nowMs), [nowMs]);
  const counts = useAppStore(useShallow(selectCounts));

  // Grouping mode and severity ordering are persisted (guarded storage) preferences (D-32).
  // Open-group state is lifted here, not into Tree/TreeNode, so a device-status message
  // re-rendering this route never resets it -- openKeys is a plain Set the store update has
  // no reason to touch. Sort order itself is always derived from current devices/mode/
  // orderBySeverity on every render (buildTree's own contract), never cached.
  const { mode, orderBySeverity, setMode, setOrderBySeverity } = useGroupingPrefs();
  const devices = useAppStore((s) => s.devices);
  const groups = useMemo(
    () => buildTree(devices, mode, nowMs, { orderBySeverity }),
    [devices, mode, nowMs, orderBySeverity],
  );
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

  const onModeChange = useCallback(
    (nextMode: GroupingMode) => {
      setMode(nextMode);
      // A grouping-MODE change alters the key space (different key strings per mode), so
      // openKeys is pruned to the keys present in the newly built tree rather than cleared
      // wholesale -- switching to folder and back should not lose unrelated already-open
      // state. A pure re-sort (the orderBySeverity checkbox) never reaches this code path:
      // openKeys is keyed by group identity, not position, so a re-sort cannot invalidate it.
      const nextKeys = new Set(buildTree(devices, nextMode).map((group) => group.key));
      setOpenKeys((prev) => new Set([...prev].filter((key) => nextKeys.has(key))));
    },
    [devices, setMode],
  );

  return (
    <ThreePaneLayout
      tree={
        <div className="flex h-full min-h-0 flex-col">
          <GroupingControls
            mode={mode}
            orderBySeverity={orderBySeverity}
            onModeChange={onModeChange}
            onOrderChange={setOrderBySeverity}
          />
          <div className="min-h-0 flex-1 overflow-auto">
            <Tree groups={groups} openKeys={openKeys} onToggle={onToggleGroup} />
          </div>
        </div>
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
      centreBottom={<EventHistory />}
    />
  );
}
