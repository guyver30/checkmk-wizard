// Zustand selectors derived from the store's raw slices.
//
// selectStateCounts/makeSelectStateCounts port the per-state counting logic from
// dashboard/js/render-index.js's countsByState() -- kept deliberately separate from the
// grouped fleet overview (cardElement/buildOverview/etc.) that D-27 supersedes and deletes;
// only the counting is ported, the overview cards are not.

import type { AppState, ConnectionPhase } from "./useAppStore";
import { displayState } from "../lib/display";
import { unmanagedIdsFromTopology } from "../lib/topologyLayout";
import type { DeviceState } from "../lib/types";

export type StateCounts = Record<DeviceState | "STALE" | "UNMANAGED", number>;

const ZERO_COUNTS: StateCounts = {
  OK: 0,
  PEND: 0,
  WARN: 0,
  UNKNOWN: 0,
  CRIT: 0,
  UNREACH: 0,
  DOWN: 0,
  STALE: 0,
  UNMANAGED: 0,
};

// A selector factory rather than a fixed `Date.now()` captured at module load, so callers
// (and tests) control the instant staleness is judged against -- the component passes a
// value derived from its own render, never a clock read at import time.
export function makeSelectStateCounts(nowMs: number = Date.now()) {
  return function selectStateCounts(state: AppState): StateCounts {
    const counts: StateCounts = { ...ZERO_COUNTS };
    const unmanagedIds = unmanagedIdsFromTopology(state.topology?.devices);
    for (const [id, device] of Object.entries(state.devices)) {
      // Staleness overrides the reported state (D-15) -- a stale device counts once, under
      // STALE, and never also under its reported state. An unmanaged switch with no real
      // state counts under UNMANAGED, never OK/UNKNOWN/STALE.
      const key = displayState(device, unmanagedIds.has(id), nowMs) as keyof StateCounts;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  };
}

export const selectStateCounts = makeSelectStateCounts();

export function selectConnectionPhase(state: AppState): ConnectionPhase {
  return state.connection.phase;
}
