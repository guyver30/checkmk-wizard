import { useState } from "react";
import { readJson, writeJson } from "../lib/guardedStorage";

// Versioned so a future shape change to the persisted record can never be misread as a
// valid one -- bump the suffix, not the key body, if the shape changes.
const STORAGE_KEY = "dashboard-react.paneLayout.v1";

const DEFAULTS = {
  treeWidth: 320,
  eventsHeight: 260,
} as const;

export const PANE_BOUNDS = {
  tree: { min: 200, max: 640 },
  events: { min: 120, max: 600 },
} as const;

interface PersistedLayout {
  treeWidth: number;
  eventsHeight: number;
  treeCollapsed: boolean;
  eventsCollapsed: boolean;
}

interface PaneSizes {
  tree: number;
  events: number;
}

interface PaneCollapsed {
  tree: boolean;
  events: boolean;
}

type PaneKey = keyof PaneSizes;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function readInitialState(): { sizes: PaneSizes; collapsed: PaneCollapsed } {
  // D-26: pane geometry lives in this hook's React state, not in any time-derived render
  // path, so a resize can never be undone by the page-wide clock's next tick -- there is no
  // effect here that could race a re-read against a later write.
  const persisted = readJson<Partial<PersistedLayout>>(STORAGE_KEY, {});

  // Clamp and fall back per-field so one corrupt/out-of-range field doesn't discard a good
  // sibling -- a whole-record fallback would throw away a valid treeWidth just because
  // eventsCollapsed was garbage, for example.
  const treeWidth =
    typeof persisted.treeWidth === "number"
      ? clamp(persisted.treeWidth, PANE_BOUNDS.tree.min, PANE_BOUNDS.tree.max)
      : DEFAULTS.treeWidth;
  const eventsHeight =
    typeof persisted.eventsHeight === "number"
      ? clamp(persisted.eventsHeight, PANE_BOUNDS.events.min, PANE_BOUNDS.events.max)
      : DEFAULTS.eventsHeight;
  const treeCollapsed = typeof persisted.treeCollapsed === "boolean" ? persisted.treeCollapsed : false;
  const eventsCollapsed = typeof persisted.eventsCollapsed === "boolean" ? persisted.eventsCollapsed : false;

  return {
    sizes: { tree: treeWidth, events: eventsHeight },
    collapsed: { tree: treeCollapsed, events: eventsCollapsed },
  };
}

export function usePaneLayout() {
  // Lazy initialiser: read persisted state ONCE, synchronously, on first render. Doing this
  // in a useEffect instead would render the defaults first and flash to the persisted sizes
  // a tick later.
  const [state, setState] = useState(readInitialState);

  function setSize(pane: PaneKey, next: number) {
    const bounds = PANE_BOUNDS[pane];
    const clamped = clamp(next, bounds.min, bounds.max);
    setState((prev) => ({ ...prev, sizes: { ...prev.sizes, [pane]: clamped } }));
  }

  function toggleCollapse(pane: PaneKey) {
    setState((prev) => {
      const next = { ...prev, collapsed: { ...prev.collapsed, [pane]: !prev.collapsed[pane] } };
      // Collapsing does not discard the stored size -- prev.sizes is carried through
      // unchanged, so restoring returns to the previous size rather than the default.
      writeJson(STORAGE_KEY, {
        treeWidth: next.sizes.tree,
        eventsHeight: next.sizes.events,
        treeCollapsed: next.collapsed.tree,
        eventsCollapsed: next.collapsed.events,
      });
      return next;
    });
  }

  function commit() {
    // A refused write must never break the interaction and must never roll the in-memory
    // value back -- writeJson's return value is deliberately ignored. React state is already
    // the source of truth (D-26); storage is only how it survives a reload.
    writeJson(STORAGE_KEY, {
      treeWidth: state.sizes.tree,
      eventsHeight: state.sizes.events,
      treeCollapsed: state.collapsed.tree,
      eventsCollapsed: state.collapsed.events,
    });
  }

  return {
    sizes: state.sizes,
    collapsed: state.collapsed,
    setSize,
    toggleCollapse,
    commit,
    bounds: PANE_BOUNDS,
  };
}
