// Kiosk mode's rotation clock (DASH-17, D-14). useNowTick's own header comment says "this is
// the app's only periodic timer -- IndexRoute must not add a second one"; this is the second,
// explicitly sanctioned exception to that rule, because it is mounted only by KioskView under
// ?kiosk=1 (IndexRoute itself never mounts it), so the two timers never coexist for the same
// operator-facing route.

import { useEffect, useState } from "react";

export const KIOSK_ROTATION_MS = 20000;

export type KioskViewName = "incidents" | "topology";

export function useKioskRotation(intervalMs: number = KIOSK_ROTATION_MS): {
  view: KioskViewName;
  cycle: number;
} {
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setCycle((c) => c + 1);
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return { view: cycle % 2 === 0 ? "incidents" : "topology", cycle };
}
