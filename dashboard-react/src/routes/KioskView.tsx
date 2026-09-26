// Kiosk mode's full-bleed rotating view (DASH-17, D-14): unattended lobby/boardroom signage
// showing open incidents and the topology map in turn, with no chrome and no write path.
//
// Read-only by construction, independent of isTopologyEditingConfigured() (T-14-16 defense in
// depth) -- editMode is always false here and the manipulation-toolbar component is never
// imported, so an edit affordance cannot appear on this route even if the app is deployed with
// a topology_editor secret configured.

import { useEffect, useMemo, useState } from "react";
import { Button } from "kone-design-system";
import { IncidentList } from "../components/IncidentList";
import { TopologyMap } from "../components/TopologyMap";
import { KIOSK_ROTATION_MS, useKioskRotation, type KioskViewName } from "../hooks/useKioskRotation";
import { useNowTick } from "../hooks/useNowTick";
import { buildIncidentLookup, selectOpenIncidents } from "../lib/incidents";
import { useAppStore } from "../store/useAppStore";

const VIEW_LABELS: Record<KioskViewName, string> = {
  incidents: "Incidents",
  topology: "Topology",
};

// A one-time affordance (Pitfall 3: requestFullscreen requires a user gesture, so it is never
// called from an effect). Shown once per page load, hidden after it is pressed or after 10s of
// no interaction -- it does not reappear on its own; a page reload brings it back.
const FULLSCREEN_BUTTON_TIMEOUT_MS = 10000;

export function KioskView() {
  const nowMs = useNowTick();
  const { view, cycle } = useKioskRotation();

  const devices = useAppStore((s) => s.devices);
  const topology = useAppStore((s) => s.topology);
  const topologyDevices = useMemo(
    () => (Array.isArray(topology?.devices) ? topology.devices : []),
    [topology],
  );
  const incidentRecord = useAppStore((s) => s.incidents);
  const incidents = useMemo(() => selectOpenIncidents(incidentRecord), [incidentRecord]);
  const incidentLookup = useMemo(() => buildIncidentLookup(incidents), [incidents]);

  const [showFullscreenButton, setShowFullscreenButton] = useState(true);

  useEffect(() => {
    const id = setTimeout(() => setShowFullscreenButton(false), FULLSCREEN_BUTTON_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, []);

  const onEnterFullscreen = () => {
    document.documentElement.requestFullscreen?.().catch(() => {});
    setShowFullscreenButton(false);
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-bg-canvas p-4 text-[1.15em]">
      <div
        data-testid="kiosk-view-incidents"
        aria-hidden={view !== "incidents"}
        className={
          view === "incidents"
            ? "absolute inset-4 opacity-100 transition-opacity duration-300"
            : "absolute inset-4 pointer-events-none opacity-0 transition-opacity duration-300"
        }
      >
        <IncidentList incidents={incidents} devices={devices} nowMs={nowMs} fill />
      </div>
      <div
        data-testid="kiosk-view-topology"
        aria-hidden={view !== "topology"}
        className={
          view === "topology"
            ? "absolute inset-4 opacity-100 transition-opacity duration-300"
            : "absolute inset-4 pointer-events-none opacity-0 transition-opacity duration-300"
        }
      >
        <TopologyMap
          topologyDevices={topologyDevices}
          statuses={devices}
          nowMs={nowMs}
          editMode={false}
          incidentLookup={incidentLookup}
        />
      </div>
      <span aria-live="polite" className="absolute bottom-2 left-4 text-xs text-fg-tertiary">
        {VIEW_LABELS[view]}
      </span>
      <div
        key={cycle}
        data-testid="kiosk-progress"
        className="absolute bottom-0 left-0 h-1 bg-brand"
        style={{ animation: `kiosk-progress ${KIOSK_ROTATION_MS}ms linear forwards` }}
      />
      {showFullscreenButton && (
        <div className="absolute right-4 top-4">
          <Button variant="secondary" onClick={onEnterFullscreen}>
            Enter full screen
          </Button>
        </div>
      )}
    </div>
  );
}
