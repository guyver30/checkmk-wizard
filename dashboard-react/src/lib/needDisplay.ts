// Display constants shared by the Service needs pane and its rows: the tier badge look and
// the hh:mm clock format.

import type { NeedTier } from "./types";

type BadgeColor = "neutral" | "warning";
type BadgeVariant = "outline" | "soft" | "solid";

export const TIER_BADGE: Record<NeedTier, { color: BadgeColor; variant: BadgeVariant; label: string }> = {
  immediate: { color: "warning", variant: "solid", label: "Immediate" },
  urgent: { color: "warning", variant: "soft", label: "Urgent" },
  standard: { color: "neutral", variant: "outline", label: "Standard" },
};

const TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatClock(ms: number): string {
  return TIME_FORMAT.format(new Date(ms));
}
