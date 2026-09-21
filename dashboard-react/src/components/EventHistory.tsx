// The centre-bottom event history pane. Reads events/devices from the store and renders
// EventRows newest-first (D-33) with legible device identification (D-35, see EventRow.tsx).

import { useAppStore } from "../store/useAppStore";
import { EventRow } from "./EventRow";

const NO_EVENTS_TEXT = "No recent events";

export function EventHistory() {
  const events = useAppStore((s) => s.events);
  const devices = useAppStore((s) => s.devices);

  if (events.length === 0) {
    return (
      <div role="log" aria-label="Recent events" aria-live="polite" className="p-3 text-sm text-fg-tertiary">
        {NO_EVENTS_TEXT}
      </div>
    );
  }

  // Newest-first: the poller appends chronologically (mqtt_poller.py's events_this_cycle is
  // concatenated onto the END of the bounded array each cycle), so lan/events/recent arrives
  // OLDEST-first. Copying via slice() before reversing is load-bearing -- Array.prototype's
  // in-place reverse would corrupt the store's array for every other reader if applied
  // directly to it. D-33 was discharged as VERIFY-not-fix on the producer side (plan 11.1-02):
  // the shipped ordering is correct; the original oldest-on-top report came from a preview
  // harness that reversed the array before publishing. A second reversal here would recreate
  // that exact bug -- do not add one.
  const rows = events.slice().reverse();

  return (
    <div
      role="log"
      aria-label="Recent events"
      aria-live="polite"
      className="flex h-full flex-col gap-1 overflow-auto p-3"
    >
      {rows.map((entry, index) => {
        // Keyed by a stable composite, not array index alone, so React does not reuse a row
        // across a reorder when a fresh events snapshot arrives.
        const key = `${entry?.device_id ?? "unknown"}:${entry?.timestamp ?? "unknown"}:${index}`;
        const device = entry?.device_id ? devices[entry.device_id] : undefined;
        return <EventRow key={key} entry={entry} device={device} />;
      })}
    </div>
  );
}
