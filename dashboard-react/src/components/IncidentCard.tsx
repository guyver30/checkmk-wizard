// One incident, rendered as a Message-based card (DASH-14). D-04: this component must never
// assert that a device has stopped operating from UNREACH/inferred evidence alone -- confirmed-
// down and not-observable hosts are always listed and worded separately, never merged into one
// claim of failure.

import { useState } from "react";
import { Link } from "react-router";
import { Badge, Message } from "kone-design-system";
import { deviceTypeMaskUrl } from "../lib/mapIcons";
import {
  consequenceSummary,
  formatIncidentDuration,
  incidentStatus,
  type CriticalityTier,
  type Incident,
} from "../lib/incidents";

// UI-SPEC Criticality Tier Palette, exact: a second, state-palette-independent color
// dimension (D-04/D-05) -- never reuses the state palette's red/orange/green.
const CRITICALITY_BADGE: Record<
  CriticalityTier,
  { color: "neutral" | "purple"; variant: "outline" | "soft" | "solid" }
> = {
  low: { color: "neutral", variant: "outline" },
  medium: { color: "neutral", variant: "soft" },
  high: { color: "purple", variant: "soft" },
  critical: { color: "purple", variant: "solid" },
};

export interface IncidentCardProps {
  incident: Incident;
  rootLabel: string;
  nameFor: (id: string) => string;
  rootDeviceType: string | null | undefined;
  nowMs: number;
  highlighted: boolean;
}

function DeviceLinkList({ ids, nameFor }: { ids: string[]; nameFor: (id: string) => string }) {
  return (
    <span className="flex flex-col">
      {ids.map((id) => (
        <Link key={id} to={`/details?id=${encodeURIComponent(id)}`} className="underline">
          {nameFor(id)}
        </Link>
      ))}
    </span>
  );
}

export function IncidentCard({
  incident,
  rootLabel,
  nameFor,
  rootDeviceType,
  nowMs,
  highlighted,
}: IncidentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const status = incidentStatus(incident);
  const summary = consequenceSummary(incident);
  const criticalityBadge = CRITICALITY_BADGE[incident.worstCriticality];

  return (
    <div
      data-incident-id={incident.id}
      data-status={status}
      className={highlighted ? "rounded-md ring-2 ring-brand" : undefined}
    >
      <Message
        shadow={false}
        status={status}
        icon={
          <span
            aria-hidden
            className="inline-block h-4 w-4 bg-current"
            style={{
              maskImage: deviceTypeMaskUrl(rootDeviceType),
              WebkitMaskImage: deviceTypeMaskUrl(rootDeviceType),
              maskSize: "contain",
              WebkitMaskSize: "contain",
              maskRepeat: "no-repeat",
              WebkitMaskRepeat: "no-repeat",
            }}
          />
        }
        title={
          <span className="flex items-center gap-1">
            {`${rootLabel} — ${formatIncidentDuration(incident.since, nowMs)}`}
            {incident.inferred && (
              <Badge color="neutral" variant="outline">
                Inferred, not confirmed
              </Badge>
            )}
          </span>
        }
        description={
          <span className="flex flex-col items-start gap-1">
            {summary && <span className="text-xs">{summary}</span>}
            <Badge color={criticalityBadge.color} variant={criticalityBadge.variant}>
              {incident.worstCriticality}
            </Badge>
            <button
              type="button"
              className="text-xs underline"
              onClick={() => setExpanded((value) => !value)}
            >
              View devices
            </button>
            {expanded && (
              <span className="mt-1 flex flex-col gap-1 text-xs">
                {incident.confirmedDown.length > 0 && (
                  <span className="flex flex-col">
                    <span className="font-semibold">Confirmed down</span>
                    <DeviceLinkList ids={incident.confirmedDown} nameFor={nameFor} />
                  </span>
                )}
                {incident.notObservable.length > 0 && (
                  <span className="flex flex-col">
                    <span className="font-semibold">Not observable</span>
                    <DeviceLinkList ids={incident.notObservable} nameFor={nameFor} />
                  </span>
                )}
                {incident.dependents.length > 0 && (
                  <span>Dependent devices: {incident.dependents.map((id) => nameFor(id)).join(", ")}</span>
                )}
              </span>
            )}
          </span>
        }
      />
    </div>
  );
}
