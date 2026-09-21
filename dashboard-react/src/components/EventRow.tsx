// One row in the centre-bottom event history pane. Ports the time / device-name / from→to
// structure of dashboard/js/render-shell.js's eventRowElement() into a component, applying
// D-35's full rule for the device column: prefer the alias (displayName), fall back to the
// raw device_id, middle-truncate whatever that produced, and always keep the untruncated
// value one hover (or `title`) away.

import { Tooltip } from "kone-design-system";
import { displayName, formatClock } from "../lib/display";
import { middleTruncate } from "../lib/truncate";
import type { DevicePayload, EventEntry } from "../lib/types";
import { StateBadgeForState } from "./StateBadge";

const DEFAULT_LABEL_BUDGET = 28;

export interface EventRowProps {
  entry: EventEntry | null | undefined;
  device?: DevicePayload;
  labelBudget?: number;
}

export function EventRow({ entry, device, labelBudget = DEFAULT_LABEL_BUDGET }: EventRowProps) {
  const deviceId = typeof entry?.device_id === "string" ? entry.device_id : "";
  // Alias-first (D-18) when the device is known to the store; a device absent from the store
  // (e.g. a "removed" event, or a message arriving before the retained status snapshot) falls
  // back to the raw id straight off the wire.
  const rawLabel = device ? displayName(device) : deviceId;
  const truncatedLabel = middleTruncate(rawLabel, labelBudget);
  const fromState = typeof entry?.from === "string" ? entry.from : "UNKNOWN";
  const toState = typeof entry?.to === "string" ? entry.to : "UNKNOWN";

  return (
    <div className="flex items-center gap-2 py-1.5 text-sm">
      <span className="shrink-0 font-mono text-xs text-fg-tertiary">
        {formatClock(entry?.timestamp)}
      </span>
      <Tooltip content={rawLabel} position="top">
        <span className="min-w-0 flex-1 truncate text-fg-primary" title={rawLabel}>
          {truncatedLabel}
        </span>
      </Tooltip>
      <span className="flex shrink-0 items-center gap-1">
        <StateBadgeForState state={fromState} />
        <span aria-hidden>→</span>
        <StateBadgeForState state={toState} />
      </span>
    </div>
  );
}
