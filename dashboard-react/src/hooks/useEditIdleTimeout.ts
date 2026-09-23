// Idle auto-exit timer for the topology map's edit mode. A tab left with "Edit topology" on
// is the residual risk once a stray drag on a shared/kiosk display is already ruled out by the
// D-02 toggle itself -- this hook covers the case where the toggle is switched on and then the
// tab is simply left alone. Fires `onTimeout` once after `timeoutMs` of no map interaction
// (pointerdown/wheel/keydown, reported via `touch()`), re-arming on every touch.

import { useEffect, useRef } from "react";

export const EDIT_IDLE_TIMEOUT_MS = 5 * 60 * 1000;

export function useEditIdleTimeout(
  active: boolean,
  onTimeout: () => void,
  timeoutMs: number = EDIT_IDLE_TIMEOUT_MS,
): { touch: () => void } {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTimeoutRef = useRef(onTimeout);

  useEffect(() => {
    onTimeoutRef.current = onTimeout;
  }, [onTimeout]);

  function clear() {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }

  function arm() {
    clear();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      onTimeoutRef.current();
    }, timeoutMs);
  }

  // arm/clear close over stable refs (timerRef/onTimeoutRef), so re-running this effect only on
  // [active, timeoutMs] is intentional -- they always read the latest onTimeout through the ref.
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (active) {
      arm();
    } else {
      clear();
    }
    return clear;
  }, [active, timeoutMs]);
  /* eslint-enable react-hooks/exhaustive-deps */

  function touch() {
    if (active) {
      arm();
    }
  }

  return { touch };
}
