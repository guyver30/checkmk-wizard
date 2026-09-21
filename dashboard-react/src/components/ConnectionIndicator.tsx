// DASH-05's connection-status indicator. RESEARCH identified `StatusBadge` (a colored dot
// paired with text) as an incidental near-exact fit for a connection indicator specifically --
// distinct from the 5-device-state Badge mapping in stateMapping.ts -- so it is used here
// directly rather than reaching for `Badge` or hand-rolling the Phase 11 connection dot, whose
// ring engineering (D-39) is explicitly dropped by D-43.

import type { StatusBadgeStatus } from "kone-design-system";
import { StatusBadge } from "kone-design-system";
import { useAppStore } from "../store/useAppStore";

export function ConnectionIndicator() {
  // Reads the full connection slice (not just selectConnectionPhase) because the
  // "reconnecting" phase's text names the store's own retry delay, not a hardcoded string.
  const { phase, delayMs } = useAppStore((state) => state.connection);

  let status: StatusBadgeStatus;
  let text: string;
  switch (phase) {
    case "connected":
      status = "connected";
      text = "Connected";
      break;
    case "reconnecting": {
      status = "low-signal";
      const seconds = Math.round((delayMs ?? 0) / 1000);
      text = `Reconnecting in ${seconds}s…`;
      break;
    }
    case "disconnected":
      status = "entrapment";
      text = "Disconnected";
      break;
    case "connecting":
    default:
      status = "unknown";
      text = "Connecting…";
      break;
  }

  return (
    <span role="status" aria-live="polite">
      <StatusBadge status={status}>{text}</StatusBadge>
    </span>
  );
}
