import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useShallow } from "zustand/shallow";
import { Snackbar } from "kone-design-system";
import { EventHistory } from "../components/EventHistory";
import { GroupingControls } from "../components/GroupingControls";
import { StatsStrip } from "../components/StatsStrip";
import { ThreePaneLayout } from "../components/ThreePaneLayout";
import { TopologyMap, type EditFailure } from "../components/TopologyMap";
import { TopologyToolbar } from "../components/TopologyToolbar";
import { Tree } from "../components/Tree";
import { useEditIdleTimeout } from "../hooks/useEditIdleTimeout";
import { useGroupingPrefs } from "../hooks/useGroupingPrefs";
import { useNowTick } from "../hooks/useNowTick";
import { activateChanges, countPendingChanges } from "../lib/checkmkWrite";
import { isTopologyEditingConfigured } from "../lib/config";
import { buildTree } from "../lib/treeModel";
import type { GroupingMode } from "../lib/types";
import { makeSelectStateCounts } from "../store/selectors";
import { useAppStore } from "../store/useAppStore";

interface SnackbarState {
  status: "success" | "danger" | "info";
  message: ReactNode;
  autoDismissMs?: number;
}

const APPLY_FAILURE_BODY =
  "Your changes are stored but Activate Changes failed. Press Apply changes again, or finish activation directly in Checkmk.";

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

  const topology = useAppStore((s) => s.topology);
  const topologyDevices = useMemo(
    () => (Array.isArray(topology?.devices) ? topology.devices : []),
    [topology],
  );

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

  // Edit-topology UI-session state (D-02): never persisted (guarded storage or otherwise) --
  // the toggle must start off on every page load, same "lift into the route, not the store"
  // rule openKeys above already follows. pendingCount is tracked client-side, incremented by
  // every onEditSaved call from the map and reset only by a successful Apply.
  const [editMode, setEditMode] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [applying, setApplying] = useState(false);
  const [snackbar, setSnackbar] = useState<SnackbarState | null>(null);

  const onEditModeChange = useCallback((next: boolean) => {
    setEditMode(next);
    if (next) {
      // Best-effort: the Banner's count is informational, so a failed read just leaves the
      // count at whatever the client already tracked, with no error surfaced for it.
      countPendingChanges()
        .then((count) => setPendingCount(count))
        .catch(() => {});
    }
  }, []);

  const { touch } = useEditIdleTimeout(editMode, () => {
    setEditMode(false);
    setSnackbar({ status: "info", message: "Edit topology turned off after 5 minutes of inactivity" });
  });

  const onEditSaved = useCallback(() => {
    setPendingCount((c) => c + 1);
    touch();
  }, [touch]);

  const onEditFailed = useCallback(({ title, body }: EditFailure) => {
    setSnackbar({
      status: "danger",
      message: (
        <>
          <span className="font-semibold">{title}</span> {body}
        </>
      ),
    });
  }, []);

  // Guarded against re-entry: a second press while the first activation is still in flight is
  // a no-op, matching the Button's own disabled/loading state in TopologyToolbar. Never
  // retried in the background on failure -- the operator presses Apply again to retry.
  const onApply = useCallback(() => {
    if (applying) {
      return;
    }
    setApplying(true);
    activateChanges()
      .then(() => {
        setPendingCount(0);
        setSnackbar({ status: "success", message: "Topology updated", autoDismissMs: 3000 });
      })
      .catch(() => {
        setSnackbar({
          status: "danger",
          message: (
            <>
              <span className="font-semibold">Saved, but not live yet</span> {APPLY_FAILURE_BODY}
            </>
          ),
        });
      })
      .finally(() => setApplying(false));
  }, [applying]);

  useEffect(() => {
    if (!snackbar?.autoDismissMs) {
      return;
    }
    const id = setTimeout(() => setSnackbar(null), snackbar.autoDismissMs);
    return () => clearTimeout(id);
  }, [snackbar]);

  return (
    <>
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
          // D-25: the stats strip sits ABOVE the map, content-sized, with the map taking the
          // remaining height -- both are always visible together. Pointer/wheel/key activity
          // anywhere in the toolbar+map wrapper below postpones the edit-mode idle timeout.
          <div className="flex h-full flex-col gap-2 p-3">
            <StatsStrip counts={counts} />
            <div
              className="flex min-h-0 flex-1 flex-col gap-2"
              onPointerDown={touch}
              onWheel={touch}
              onKeyDown={touch}
            >
              <TopologyToolbar
                editMode={editMode}
                onEditModeChange={onEditModeChange}
                pendingCount={pendingCount}
                applying={applying}
                onApply={onApply}
                editingConfigured={isTopologyEditingConfigured()}
              />
              <div className="min-h-0 flex-1">
                <TopologyMap
                  topologyDevices={topologyDevices}
                  statuses={devices}
                  nowMs={nowMs}
                  editMode={editMode}
                  onEditSaved={onEditSaved}
                  onEditFailed={onEditFailed}
                />
              </div>
            </div>
          </div>
        }
        centreBottom={<EventHistory />}
      />
      {snackbar && (
        <div className="fixed bottom-4 right-4 z-50" data-testid="snackbar">
          <Snackbar
            status={snackbar.status}
            message={snackbar.message}
            actionLabel="Dismiss"
            onAction={() => setSnackbar(null)}
          />
        </div>
      )}
    </>
  );
}
