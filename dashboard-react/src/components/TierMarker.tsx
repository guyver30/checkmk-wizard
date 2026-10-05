// Service-need tier marker for tree rows: a small element separate from the state badge, so the
// tier (a third dimension beside state and criticality) never recolours or replaces the state.
// Every tier is a filled dot: red immediate, orange urgent, yellow standard (2026-10-05, operator
// request; standard used to draw nothing and urgent was a ring). Colour is never the only signal:
// each dot carries an aria-label naming its tier. The narration, when given, is the analytics
// service's own text and is shown only as a tooltip text node.

import { Tooltip } from "kone-design-system";
import type { NeedTier } from "../lib/types";

export interface TierMarkerProps {
  tier: NeedTier;
  narration?: string;
}

// The design system has no yellow token, so standard uses a fixed Tailwind-yellow hex.
const MARKER: Record<NeedTier, { label: string; className: string }> = {
  immediate: { label: "Immediate service need", className: "bg-alert" },
  urgent: { label: "Urgent service need", className: "bg-warning" },
  standard: { label: "Standard service need", className: "bg-[#facc15]" },
};

export function TierMarker({ tier, narration }: TierMarkerProps) {
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
