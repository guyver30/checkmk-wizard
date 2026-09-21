// Device-state -> Badge visual mapping (D-44). D-11's state color MEANINGS are unchanged
// from Phase 11 -- only the SOURCE of the color/icon values moved, from a hand-rolled
// `--state-*` token system to kone-design-system's own `Badge` primitive (`color`/`variant`/
// `icon`). See 11.1-RESEARCH.md's "D-44 Research Answer" for why `Badge` was chosen over
// `Chip`/`Banner`/`Message` (none of the four has a dedicated critical/down variant distinct
// from a generic "danger").
//
// STALE and UNKNOWN are deliberately given different colors AND different icons, so the two
// are never distinguishable by color alone -- STALE ("no fresh data") is not itself a health
// judgment, whereas UNKNOWN really is an unrecognised/unparseable state.
//
// CRIT and UNREACH both map to `danger` because the library has exactly one negative-severity
// color -- variant (`soft` vs `outline`, distinct from DOWN's `solid`) is the only available
// differentiator between them. This is a documented library limitation, not a design choice.

import type { BadgeColor, BadgeVariant } from "kone-design-system";

export interface BadgeSpec {
  color: BadgeColor;
  variant: BadgeVariant;
  iconName: string | null;
  label: string;
}

// Locked UI-SPEC icon class-name strings (display.ts's stateIcon table plus the two this
// module adds for the derived pseudo-state STALE and the icon-disambiguated UNKNOWN).
const ICON_CLOCK = "icon-clock";
const ICON_QUESTION = "icon-question-circle-filled";

const STATE_SPECS: Record<string, BadgeSpec> = {
  OK: { color: "success", variant: "soft", iconName: null, label: "OK" },
  PEND: { color: "neutral", variant: "soft", iconName: null, label: "PEND" },
  WARN: { color: "warning", variant: "soft", iconName: null, label: "WARN" },
  UNKNOWN: { color: "black", variant: "soft", iconName: ICON_QUESTION, label: "UNKNOWN" },
  CRIT: { color: "danger", variant: "soft", iconName: null, label: "CRIT" },
  UNREACH: { color: "danger", variant: "outline", iconName: null, label: "UNREACH" },
  DOWN: { color: "danger", variant: "solid", iconName: null, label: "DOWN" },
  STALE: { color: "neutral", variant: "outline", iconName: ICON_CLOCK, label: "STALE" },
};

export function badgeForState(state: string): BadgeSpec {
  return STATE_SPECS[state] ?? STATE_SPECS.UNKNOWN;
}
