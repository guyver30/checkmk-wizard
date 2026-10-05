import { useState } from "react";
import { readJson, writeJson } from "../lib/guardedStorage";

// Versioned so a future shape change to the persisted record can never be misread as a
// valid one -- bump the suffix, not the key body, if the shape changes. The details pane
// fields added below (260928-l4h) do NOT bump this to v2: the addition is purely additive and
// readInitialState's per-field fallback already handles a v1 record that predates them, so
// bumping would needlessly discard an operator's saved tree/events sizes. The incidents pane
// fields are additive in the same way. `sizes.details` is the width of the whole right column
// (the incidents and details panes share it); it keeps the `details` key so a width saved
// before the incidents pane existed still applies.
const STORAGE_KEY = "dashboard-react.paneLayout.v1";

const DEFAULTS = {
  treeWidth: 320,
  eventsHeight: 260,
  detailsWidth: 420,
  incidentsHeight: 280,
} as const;

export const PANE_BOUNDS = {
  tree: { min: 200, max: 640 },
  events: { min: 120, max: 600 },
  details: { min: 280, max: 800 },
  incidents: { min: 120, max: 600 },
} as const;

interface PersistedLayout {
  treeWidth: number;
  eventsHeight: number;
  treeCollapsed: boolean;
  eventsCollapsed: boolean;
  detailsWidth: number;
  detailsCollapsed: boolean;
  incidentsHeight: number;
  incidentsCollapsed: boolean;
}

interface PaneSizes {
  tree: number;
  events: number;
  details: number;
  incidents: number;
}

interface PaneCollapsed {
  tree: boolean;
  events: boolean;
  details: boolean;
  incidents: boolean;
}

type PaneKey = keyof PaneSizes;
type CollapsibleKey = keyof PaneCollapsed;

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
  const detailsWidth =
    typeof persisted.detailsWidth === "number"
      ? clamp(persisted.detailsWidth, PANE_BOUNDS.details.min, PANE_BOUNDS.details.max)
      : DEFAULTS.detailsWidth;
  const detailsCollapsed =
    typeof persisted.detailsCollapsed === "boolean" ? persisted.detailsCollapsed : false;
  const incidentsHeight =
    typeof persisted.incidentsHeight === "number"
      ? clamp(persisted.incidentsHeight, PANE_BOUNDS.incidents.min, PANE_BOUNDS.incidents.max)
      : DEFAULTS.incidentsHeight;
  const incidentsCollapsed =
    typeof persisted.incidentsCollapsed === "boolean" ? persisted.incidentsCollapsed : false;

  return {
    sizes: { tree: treeWidth, events: eventsHeight, details: detailsWidth, incidents: incidentsHeight },
    collapsed: {
      tree: treeCollapsed,
      events: eventsCollapsed,
      details: detailsCollapsed,
      incidents: incidentsCollapsed,
    },
  };
}

interface LayoutState {
  sizes: PaneSizes;
  collapsed: PaneCollapsed;
}

function toRecord(state: LayoutState): PersistedLayout {
  return {
    treeWidth: state.sizes.tree,
    eventsHeight: state.sizes.events,
    treeCollapsed: state.collapsed.tree,
    eventsCollapsed: state.collapsed.events,
    detailsWidth: state.sizes.details,
    detailsCollapsed: state.collapsed.details,
    incidentsHeight: state.sizes.incidents,
    incidentsCollapsed: state.collapsed.incidents,
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

  function toggleCollapse(pane: CollapsibleKey) {
    setState((prev) => {
      const next = { ...prev, collapsed: { ...prev.collapsed, [pane]: !prev.collapsed[pane] } };
      // Collapsing does not discard the stored size -- prev.sizes is carried through
      // unchanged, so restoring returns to the previous size rather than the default.
      writeJson(STORAGE_KEY, toRecord(next));
      return next;
    });
  }

  // Sets a pane's collapsed flag to false and persists -- a no-op state change if it's already
  // expanded. Used by ThreePaneLayout to re-expand the details pane when a new host opens while
  // it's collapsed (operator decision 3).
  function expand(pane: CollapsibleKey) {
    setState((prev) => {
      if (!prev.collapsed[pane]) {
        return prev;
      }
      const next = { ...prev, collapsed: { ...prev.collapsed, [pane]: false } };
      writeJson(STORAGE_KEY, toRecord(next));
      return next;
    });
  }

  function commit() {
    // A refused write must never break the interaction and must never roll the in-memory
    // value back -- writeJson's return value is deliberately ignored. React state is already
    // the source of truth (D-26); storage is only how it survives a reload.
    writeJson(STORAGE_KEY, toRecord(state));
  }

  return {
    sizes: state.sizes,
    collapsed: state.collapsed,
    setSize,
    toggleCollapse,
    expand,
    commit,
    bounds: PANE_BOUNDS,
  };
}
