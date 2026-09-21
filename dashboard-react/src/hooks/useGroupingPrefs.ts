import { useState } from "react";
import { readJson, writeJson } from "../lib/guardedStorage";
import type { GroupingMode } from "../lib/types";

// Versioned so a future shape change to the persisted record can never be misread as a valid
// one -- bump the suffix, not the key body, if the shape changes.
const STORAGE_KEY = "dashboard-react.grouping.v1";

const DEFAULTS: PersistedGroupingPrefs = { mode: "type", orderBySeverity: false };

interface PersistedGroupingPrefs {
  mode: GroupingMode;
  orderBySeverity: boolean;
}

// The list of modes this hook accepts, expressed as data rather than a chain of `=== "type"
// || === "folder"` comparisons, so a stored value is validated by membership rather than by
// hardcoded branching (T-11.1-12). `GroupingControls.tsx`'s own `GROUPING_OPTIONS` (plan
// 11.1-09 Task 2) is the operator-facing source for these same two values; this hook has no
// import-time dependency on that component, so the two lists are kept in step by hand --
// adding a third mode touches both, exactly as `GroupingMode`'s own type union would.
const KNOWN_MODES: readonly GroupingMode[] = ["type", "folder"];

function isKnownMode(value: unknown): value is GroupingMode {
  return typeof value === "string" && (KNOWN_MODES as readonly string[]).includes(value);
}

function readInitialState(): PersistedGroupingPrefs {
  const persisted = readJson<Partial<PersistedGroupingPrefs>>(STORAGE_KEY, {});

  // Per-field validation with independent fallbacks, mirroring usePaneLayout: a corrupt
  // orderBySeverity must not discard a valid stored mode, and vice versa. `mode` is
  // validated against KNOWN_MODES's value list (T-11.1-12) rather than a chain of hardcoded
  // comparisons, so a stored value the app no longer recognises -- an old option that was
  // removed, or a tampered value -- never reaches groupKeyFor and instead falls back to
  // "type".
  const mode = isKnownMode(persisted.mode) ? persisted.mode : DEFAULTS.mode;
  const orderBySeverity =
    typeof persisted.orderBySeverity === "boolean" ? persisted.orderBySeverity : DEFAULTS.orderBySeverity;

  return { mode, orderBySeverity };
}

export function useGroupingPrefs() {
  // Lazy initialiser: read persisted state ONCE, synchronously, on first render -- doing this
  // in a useEffect instead would render the defaults first and flash to the persisted choice
  // a tick later.
  const [state, setState] = useState(readInitialState);

  function setMode(mode: GroupingMode) {
    setState((prev) => {
      const next = { ...prev, mode };
      // In-memory state is already the source of truth for the session (D-26); a refused
      // write must never break the interaction, so writeJson's return value is deliberately
      // ignored here.
      writeJson(STORAGE_KEY, next);
      return next;
    });
  }

  function setOrderBySeverity(orderBySeverity: boolean) {
    setState((prev) => {
      const next = { ...prev, orderBySeverity };
      writeJson(STORAGE_KEY, next);
      return next;
    });
  }

  return {
    mode: state.mode,
    orderBySeverity: state.orderBySeverity,
    setMode,
    setOrderBySeverity,
  };
}
