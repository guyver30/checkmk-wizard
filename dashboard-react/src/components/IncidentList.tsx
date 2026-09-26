// DASH-14's ordered incident card list, plus its "No open incidents" empty state. Incidents
// are expected already sorted (selectOpenIncidents's D-12 ordering) -- this component never
// re-sorts them.

import { useEffect, useRef } from "react";
import { displayName } from "../lib/display";
import type { Incident } from "../lib/incidents";
import type { DevicePayload } from "../lib/types";
import { IncidentCard } from "./IncidentCard";

export interface IncidentListProps {
  incidents: Incident[];
  devices: Record<string, DevicePayload>;
  nowMs: number;
  highlightedId?: string | null;
  fill?: boolean;
}

export function IncidentList({ incidents, devices, nowMs, highlightedId, fill = false }: IncidentListProps) {
  const sectionRef = useRef<HTMLElement | null>(null);

  // T-14-12: `highlightedId` comes from the `?incident=` query string (user-controllable). An
  // unmatched or malformed value must highlight nothing and never throw.
  useEffect(() => {
    if (!highlightedId || !sectionRef.current) {
      return;
    }
    try {
      const escaped =
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(highlightedId)
          : highlightedId;
      const target = sectionRef.current.querySelector(`[data-incident-id="${escaped}"]`);
      target?.scrollIntoView({ block: "nearest" });
    } catch {
      // Malformed id: highlight nothing, never throw.
    }
  }, [highlightedId]);

  const nameFor = (id: string) => displayName(devices[id] ?? { id });

  if (incidents.length === 0) {
    return (
      <div className="text-xs text-fg-tertiary">
        <p className="font-semibold">No open incidents</p>
        <p>Every device the poller can reach is reporting normally.</p>
      </div>
    );
  }

  return (
    <section
      ref={sectionRef}
      aria-label="Open incidents"
      className={
        fill
          ? "flex h-full flex-col gap-2 overflow-y-auto"
          : "flex max-h-[35vh] shrink-0 flex-col gap-2 overflow-y-auto"
      }
    >
      {incidents.map((incident) => (
        <IncidentCard
          key={incident.id}
          incident={incident}
          rootLabel={nameFor(incident.root)}
          nameFor={nameFor}
          rootDeviceType={devices[incident.root]?.device_type}
          nowMs={nowMs}
          highlighted={highlightedId === incident.id}
        />
      ))}
    </section>
  );
}
