// Fixed worst-first sort order for a device's service list (D-09). Services are always
// rendered in this order -- the Table is not user-resortable (12-UI-SPEC.md Layout section).
//
// No DOM access, no store access, no network calls -- pure functions only.

import type { ServiceEntry } from "./types";

export const SEVERITY_ORDER: Record<string, number> = { CRIT: 0, WARN: 1, UNKNOWN: 2, OK: 3 };

// An unrecognised or missing state ranks with UNKNOWN (severity 2), same fallback as
// stateMapping.ts's badgeForState().
export function compareServices(a: ServiceEntry, b: ServiceEntry): number {
  const rankA = SEVERITY_ORDER[a.state ?? ""] ?? SEVERITY_ORDER.UNKNOWN;
  const rankB = SEVERITY_ORDER[b.state ?? ""] ?? SEVERITY_ORDER.UNKNOWN;
  const diff = rankA - rankB;
  if (diff !== 0) {
    return diff;
  }
  return (a.description ?? "").localeCompare(b.description ?? "");
}
