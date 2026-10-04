// Display constants shared by the Service needs pane and its rows: the tier badge look and
// the hh:mm clock format.

import type { NeedPayload, NeedTier } from "./types";

type BadgeColor = "neutral" | "warning";
type BadgeVariant = "outline" | "soft" | "solid";

export const TIER_BADGE: Record<NeedTier, { color: BadgeColor; variant: BadgeVariant; label: string }> = {
  immediate: { color: "warning", variant: "solid", label: "Immediate" },
  urgent: { color: "warning", variant: "soft", label: "Urgent" },
  standard: { color: "neutral", variant: "outline", label: "Standard" },
};

// Worst visible need per host, with that need's narration, for the tree and map markers.
// `needs` is expected worst-first (selectVisibleNeeds's order), so the first need seen per host
// is the one shown.
export type TierLookup = Record<string, { tier: NeedTier; narration: string }>;

export function buildTierLookup(needs: NeedPayload[]): TierLookup {
  const lookup: TierLookup = {};
  for (const need of needs) {
    if (!(need.host in lookup)) {
      lookup[need.host] = { tier: need.tier, narration: need.narration };
    }
  }
  return lookup;
}

const TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatClock(ms: number): string {
  return TIME_FORMAT.format(new Date(ms));
}
