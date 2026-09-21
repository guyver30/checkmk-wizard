// A single periodic clock driving every time-derived surface on the index route (device
// badge staleness, the stats-strip counts).
//
// CLOCK_TICK_MS is inherited verbatim from dashboard/js/render-shell.js line 53. In the
// vanilla implementation, each tick drove three full replaceChildren() rebuilds (the tree
// plus both view modules), so a taller tree meant strictly more DOM churn per tick -- the
// exact cost D-34's "also revisit CLOCK_TICK_MS once panes are resizable" note worried
// about. Here, a tick only advances a `nowMs` value threaded into derived props (badge
// state, stats counts); React's reconciler patches only the attributes that actually
// changed, so a taller tree does not mean more work per tick. The number is therefore NOT
// lowered -- StaleStability.test.tsx proves, against React's real re-render behavior, that a
// tick costs no UI state regardless of tree size.
//
// This is the app's only periodic timer -- IndexRoute must not add a second one.

import { useEffect, useState } from "react";

export const CLOCK_TICK_MS = 12000;

export function useNowTick(intervalMs: number = CLOCK_TICK_MS): number {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      setNowMs(Date.now());
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return nowMs;
}
