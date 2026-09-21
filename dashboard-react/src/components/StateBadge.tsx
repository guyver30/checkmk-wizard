// Renders one device's (or one bare state's) current status through kone-design-system's own
// `Badge` primitive (D-44) -- see stateMapping.ts for the color/variant/icon table and why
// STALE/UNKNOWN are separated by icon as well as color.

import { Badge } from "kone-design-system";
import { effectiveState } from "../lib/display";
import { isDeviceStale } from "../lib/staleness";
import type { DevicePayload } from "../lib/types";
import { badgeForState } from "../lib/stateMapping";

export interface StateBadgeProps {
  device: DevicePayload | null | undefined;
  nowMs?: number;
}

function Icon({ iconName }: { iconName: string | null }) {
  if (!iconName) {
    return null;
  }
  return <span className={iconName} aria-hidden />;
}

export function StateBadge({ device, nowMs = Date.now() }: StateBadgeProps) {
  // Staleness overrides the reported state (D-15) -- a device can be reporting "OK" while its
  // last update is too old to trust. `effectiveState` (never `device.state` directly) is used
  // for the non-stale path because `state` structurally cannot contain "UNREACH".
  const state = isDeviceStale(device, nowMs) ? "STALE" : effectiveState(device);
  const spec = badgeForState(state);
  return (
    <Badge color={spec.color} variant={spec.variant} icon={<Icon iconName={spec.iconName} />}>
      {state}
    </Badge>
  );
}

export function StateBadgeForState({ state }: { state: string }) {
  const spec = badgeForState(state);
  return (
    <Badge color={spec.color} variant={spec.variant} icon={<Icon iconName={spec.iconName} />}>
      {state}
    </Badge>
  );
}
