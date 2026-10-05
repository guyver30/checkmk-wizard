import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router";
import { Snackbar } from "kone-design-system";
import { AdminActionBar, AdminBanner } from "../components/AdminBar";
import { CriticalityEditor } from "../components/CriticalityEditor";
import { EventHistory } from "../components/EventHistory";
import { GroupingControls } from "../components/GroupingControls";
import { HostDetails } from "../components/HostDetails";
import { AlertsPane, AlertsSummary } from "../components/AlertsPane";
import { IncidentList } from "../components/IncidentList";
import { NeedsPane } from "../components/NeedsPane";
import { ThreePaneLayout } from "../components/ThreePaneLayout";
import { TopologyMap, type EditFailure } from "../components/TopologyMap";
import { TopologyToolbar } from "../components/TopologyToolbar";
import { Tree } from "../components/Tree";
import { isAdminMode } from "../lib/adminMode";
import { displayName } from "../lib/display";
import { useEditIdleTimeout } from "../hooks/useEditIdleTimeout";
import { useGroupingPrefs } from "../hooks/useGroupingPrefs";
import { useNowTick } from "../hooks/useNowTick";
import { displayedServices } from "../lib/agentDetail";
import {
  activateChanges,
  countPendingChanges,
  probeEditingAvailable,
} from "../lib/checkmkWrite";
import { newestGeneratedAt, selectVisibleNeeds } from "../lib/forecast";
import { buildTierLookup } from "../lib/needDisplay";
import { buildIncidentLookup, selectOpenIncidents } from "../lib/incidents";
import { buildTree } from "../lib/treeModel";
import type { GroupingMode, TopologyNode } from "../lib/types";
import { useAppStore } from "../store/useAppStore";

interface SnackbarState {
  status: "success" | "danger" | "info";
  message: ReactNode;
  autoDismissMs?: number;
}

const APPLY_FAILURE_BODY =
  "Your changes are stored but Activate Changes failed. Press Apply changes again, or finish activation directly in Checkmk.";

export function IndexRoute() {
  // useNowTick is the app's single periodic clock (D-34): it drives every time-derived surface
  // on this route so staleness becomes visible even when the poller goes silent. The fleet
  // state counts moved to the header (HeaderStats in StatsStrip.tsx, 2026-09-28).
  const nowMs = useNowTick();
  // Admin chrome (banner, action bar, tree selection) exists only with ?admin=1; admin wins
  // over topology edit mode, so the edit toggle is disabled and editMode can never turn on.
  const adminMode = isAdminMode();

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
  const { mode, orderBySeverity, setMode, setOrderBySeverity } =
    useGroupingPrefs();
  const devices = useAppStore((s) => s.devices);

  // Phase 14 / DASH-14/DASH-15: open incidents, ordered (D-12) and looked up by host id, both
  // pure derivations of the incidents store slice -- never re-sorted or re-derived downstream.
  const incidentRecord = useAppStore((s) => s.incidents);
  const incidents = useMemo(
    () => selectOpenIncidents(incidentRecord),
    [incidentRecord],
  );
  const incidentLookup = useMemo(
    () => buildIncidentLookup(incidents),
    [incidents],
  );
  // Service needs: sorted, non-cancelled list plus the freshness of the analytics output. Both
  // are derived from the store slices on every change, never cached elsewhere.
  const needRecord = useAppStore((s) => s.needs);
  const forecastRecord = useAppStore((s) => s.forecasts);
  const narrationRecord = useAppStore((s) => s.narrations);
  const reconnecting = useAppStore((s) => s.connection.phase === "reconnecting");
  const visibleNeeds = useMemo(() => selectVisibleNeeds(needRecord), [needRecord]);
  const tierLookup = useMemo(() => buildTierLookup(visibleNeeds), [visibleNeeds]);
  const needsUpdatedAtMs = useMemo(
    () => newestGeneratedAt(needRecord, forecastRecord),
    [needRecord, forecastRecord],
  );
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightedIncidentId = searchParams.get("incident");
  // The right-hand host details pane (260928-l4h): present only while ?host= is set, opened
  // from the map/tree/incident cards. Closing it clears just ?host=, leaving ?incident= (and
  // any other param) untouched -- the two params coexist (operator decision 2).
  // In admin mode a click selects hosts instead of opening details (gap 1), so a ?host= from a
  // shared link is ignored there: no details pane and no host filter on the event history.
  const hostId = adminMode ? null : searchParams.get("host");
  const onTreeBackgroundClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement;
      if (
        target.closest(
          "a, button, input, select, label, [role='treeitem'], [role='button']",
        )
      ) {
        return;
      }
      if (!searchParams.has("host")) {
        return;
      }
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("host");
        return next;
      });
    },
    [searchParams, setSearchParams],
  );
  const onCloseDetails = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("host");
      return next;
    });
  }, [setSearchParams]);

  const groups = useMemo(
    () => buildTree(devices, mode, nowMs, { orderBySeverity, incidentLookup, tierLookup }),
    [devices, mode, nowMs, orderBySeverity, incidentLookup, tierLookup],
  );
  // Hosts the dashboard currently lists, for the admin "Select all" button. "Listed" means the
  // tree model built from the live device map; collapsed groups still count because their hosts
  // stay visible on the map, and any future tree/map filter narrows `groups` and so narrows
  // Select all automatically. There is no filter control today.
  const visibleHostIds = useMemo(
    () =>
      Array.from(
        new Set(groups.flatMap((group) => group.children.map((c) => c.id))),
      ).sort(),
    [groups],
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
      const nextKeys = new Set(
        buildTree(devices, nextMode).map((group) => group.key),
      );
      setOpenKeys(
        (prev) => new Set([...prev].filter((key) => nextKeys.has(key))),
      );
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

  // Amended 2026-09-30 (quick 260930-hpy): editing availability is no longer a
  // compile-time config.ts placeholder check -- it is a runtime probe against
  // nginx's allow-listed GET /version (probeEditingAvailable()), since the
  // topology_editor credential itself never reaches the browser bundle at
  // all now. Starts false so the switch/editor stay off until the probe
  // resolves; the cancelled flag avoids setting state after unmount.
  const [editingAvailable, setEditingAvailable] = useState(false);
  useEffect(() => {
    let cancelled = false;
    probeEditingAvailable().then((available) => {
      if (!cancelled) {
        setEditingAvailable(available);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // DASH-16: the host currently selected for the "Criticality & dependencies" panel -- a map
  // click (TopologyMap's onSelectHost) or the panel's own "Device" picker, while in edit mode.
  // Reset to null when edit mode turns off, same "never persist edit-session state" rule
  // editMode/pendingCount above already follow.
  const [selectedHost, setSelectedHost] = useState<string | null>(null);
  const hostIds = useMemo(
    () =>
      Array.from(
        new Set(
          topologyDevices
            .map((entry) =>
              entry && typeof entry === "object"
                ? (entry as TopologyNode).id
                : undefined,
            )
            .filter(
              (id): id is string => typeof id === "string" && id.length > 0,
            ),
        ),
      ).sort(),
    [topologyDevices],
  );
  const selectedNode = useMemo(
    () =>
      selectedHost
        ? (topologyDevices.find(
            (entry) =>
              entry &&
              typeof entry === "object" &&
              (entry as TopologyNode).id === selectedHost,
          ) as TopologyNode | undefined)
        : undefined,
    [topologyDevices, selectedHost],
  );
  const services = useAppStore((s) => s.services);
  const serviceNames = useMemo(() => {
    if (!selectedHost) {
      return [];
    }
    // Only what the host details view shows (agent hosts: chosen services + TCP ports), so
    // the editor doesn't offer every row the poller publishes (14-09 live feedback).
    return displayedServices(services[selectedHost] ?? [])
      .map((service) => service.description)
      .filter(
        (description): description is string => typeof description === "string",
      );
  }, [services, selectedHost]);
  const nameFor = useCallback(
    (id: string) => displayName(devices[id] ?? { id }),
    [devices],
  );

  const onEditModeChange = useCallback((next: boolean) => {
    setEditMode(next);
    if (!next) {
      setSelectedHost(null);
    }
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
    setSnackbar({
      status: "info",
      message: "Edit topology turned off after 5 minutes of inactivity",
    });
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
        setSnackbar({
          status: "success",
          message: "Topology updated",
          autoDismissMs: 3000,
        });
      })
      .catch(() => {
        setSnackbar({
          status: "danger",
          message: (
            <>
              <span className="font-semibold">Saved, but not live yet</span>{" "}
              {APPLY_FAILURE_BODY}
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

  const layout = (
    <ThreePaneLayout
      tree={
        <div className="flex h-full min-h-0 flex-col">
          <GroupingControls
            mode={mode}
            orderBySeverity={orderBySeverity}
            onModeChange={onModeChange}
            onOrderChange={setOrderBySeverity}
          />
          {/* A click on empty space in the tree pane (not on a row, link or control) deselects
                the host, like a click on empty map canvas (260928 follow-up). */}
          <div
            className="min-h-0 flex-1 overflow-auto"
            onClick={onTreeBackgroundClick}
          >
            <Tree
              groups={groups}
              openKeys={openKeys}
              onToggle={onToggleGroup}
              groupingMode={mode}
            />
          </div>
        </div>
      }
      centreTop={
        // The map takes the whole centre height (the D-25 stats strip moved to the header on
        // 2026-09-28; the incident cards live in the right column's Incidents pane, above host
        // details). Pointer/wheel/key activity anywhere in the toolbar+map wrapper below
        // postpones the edit-mode idle timeout. Topology edit mode gives the map the full centre
        // area: no event history or host details pane (the alerts pane stays, Needs tab only); the device tree stays
        // (260928).
        <div className="flex h-full flex-col gap-2 p-3">
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
              editingConfigured={editingAvailable}
              disabledReason={
                adminMode ? "Unavailable in admin mode" : undefined
              }
            />
            {editMode && editingAvailable && (
              <CriticalityEditor
                hostIds={hostIds}
                nameFor={nameFor}
                selectedHost={selectedHost}
                onSelectHost={setSelectedHost}
                node={selectedNode}
                serviceNames={serviceNames}
                onSaved={onEditSaved}
                onFailed={onEditFailed}
              />
            )}
            <div className="min-h-0 flex-1">
              <TopologyMap
                topologyDevices={topologyDevices}
                statuses={devices}
                nowMs={nowMs}
                editMode={editMode}
                onEditSaved={onEditSaved}
                onEditFailed={onEditFailed}
                incidentLookup={incidentLookup}
                tierLookup={tierLookup}
                onSelectHost={setSelectedHost}
                onActivity={touch}
              />
            </div>
          </div>
        </div>
      }
      centreBottom={editMode ? undefined : <EventHistory hostId={hostId} />}
      // The right column's alerts pane is passed in every mode (2026-10-05 amendment to 14.2
      // D-24/D-25): triage lives in its Needs tab, and ?admin=1 cannot enter edit mode, so a
      // demo must be able to triage outside it. In edit mode AlertsPane disables the Incidents
      // tab and forces Needs, then restores the previous tab on exit; event history and host
      // details are still hidden in edit mode.
      alerts={
        <AlertsPane
          incidentsPanel={
            <IncidentList
              incidents={incidents}
              devices={devices}
              nowMs={nowMs}
              highlightedId={highlightedIncidentId}
              narrations={narrationRecord}
            />
          }
          needsPanel={
            <NeedsPane
              needs={visibleNeeds}
              nameFor={nameFor}
              nowMs={nowMs}
              highlightedHost={hostId ?? selectedHost}
              updatedAtMs={needsUpdatedAtMs}
              reconnecting={reconnecting}
            />
          }
          incidentCount={incidents.length}
          needCount={visibleNeeds.length}
          editMode={editMode}
          focusIncidentId={highlightedIncidentId}
        />
      }
      alertsSummary={<AlertsSummary incidents={incidents} needs={visibleNeeds} />}
      details={hostId && !editMode ? <HostDetails id={hostId} /> : undefined}
      detailsKey={hostId}
      onCloseDetails={onCloseDetails}
    />
  );

  return (
    <>
      {adminMode ? (
        <div className="flex h-full min-h-0 flex-col">
          <AdminBanner />
          <div className="min-h-0 flex-1">{layout}</div>
          <AdminActionBar
            devices={devices}
            topologyDevices={topologyDevices}
            visibleHostIds={visibleHostIds}
          />
        </div>
      ) : (
        layout
      )}
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
