// Service-need tier marker for tree rows: a small element separate from the state badge, so the
// tier (a third dimension beside state and criticality) never recolours or replaces the state.
// Immediate is a filled dot, urgent a ring, standard draws nothing. The narration, when given,
// is the analytics service's own text and is shown only as a tooltip text node.

import { Tooltip } from "kone-design-system";
import type { NeedTier } from "../lib/types";

export interface TierMarkerProps {
  tier: NeedTier;
  narration?: string;
}

const MARKER: Record<Exclude<NeedTier, "standard">, { label: string; className: string }> = {
  immediate: { label: "Immediate service need", className: "bg-warning" },
  urgent: { label: "Urgent service need", className: "border-2 border-warning" },
};

export function TierMarker({ tier, narration }: TierMarkerProps) {
  if (tier === "standard") {
    return null;
  }
  const { label, className } = MARKER[tier];
  const dot = (
    <span
      role="img"
      aria-label={label}
      data-tier={tier}
      className={`ml-1 inline-block h-2 w-2 shrink-0 rounded-full ${className}`}
    />
  );
  return narration ? (
    <Tooltip content={narration} position="top">
      {dot}
    </Tooltip>
  ) : (
    dot
  );
}
