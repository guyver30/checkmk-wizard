// The centre-bottom event history pane. Reads events/devices from the store and renders
// EventRows newest-first (D-33) with legible device identification (D-35, see EventRow.tsx).
// A From/To date-time filter above the list narrows the rows client-side.

import { useState } from "react";
import { Button, Input } from "kone-design-system";
import { filterEventsByRange, parseRangeBound } from "../lib/eventFilter";
import { useAppStore } from "../store/useAppStore";
import { EventRow } from "./EventRow";

const NO_EVENTS_TEXT = "No recent events";
const NO_EVENTS_IN_RANGE_TEXT = "No events in this range";
const REVERSED_RANGE_TEXT = "End must be after start";

export function EventHistory() {
  const events = useAppStore((s) => s.events);
  const devices = useAppStore((s) => s.devices);
  // Raw datetime-local input values ("YYYY-MM-DDTHH:MM" or "").
  const [fromValue, setFromValue] = useState("");
  const [toValue, setToValue] = useState("");

  // Newest-first: the poller appends chronologically (mqtt_poller.py's events_this_cycle is
  // concatenated onto the END of the bounded array each cycle), so lan/events/recent arrives
  // OLDEST-first. Copying via slice() before reversing is load-bearing -- Array.prototype's
  // in-place reverse would corrupt the store's array for every other reader if applied
  // directly to it. D-33 was discharged as VERIFY-not-fix on the producer side (plan 11.1-02):
  // the shipped ordering is correct; the original oldest-on-top report came from a preview
  // harness that reversed the array before publishing. A second reversal here would recreate
  // that exact bug -- do not add one.
  const rows = events.slice().reverse();

  // The feed is capped at 1000 entries by the poller, so the list can be that long; plain
  // rendering is fine at this size and no virtualisation is added.
  const { rows: visibleRows, status } = filterEventsByRange(rows, {
    from: parseRangeBound(fromValue),
    to: parseRangeBound(toValue),
  });

  const bothEmpty = fromValue === "" && toValue === "";

  return (
    <div className="flex h-full flex-col">
      {/* Outside the aria-live log so typing in the filter is not announced as log updates. */}
      <div className="flex shrink-0 items-start gap-2 p-3 pb-0">
        <Input
          id="event-filter-from"
          type="datetime-local"
          size="sm"
          label="From"
          value={fromValue}
          onChange={(e) => setFromValue(e.target.value)}
        />
        <Input
          id="event-filter-to"
          type="datetime-local"
          size="sm"
          label="To"
          value={toValue}
          error={status === "reversed" ? REVERSED_RANGE_TEXT : undefined}
          onChange={(e) => setToValue(e.target.value)}
        />
        <Button
          variant="tertiary"
          size="sm"
          disabled={bothEmpty}
          onClick={() => {
            setFromValue("");
            setToValue("");
          }}
        >
          Clear
        </Button>
      </div>
      <div
        role="log"
        aria-label="Recent events"
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto p-3"
      >
        {events.length === 0 ? (
          <div className="text-sm text-fg-tertiary">{NO_EVENTS_TEXT}</div>
        ) : visibleRows.length === 0 ? (
          <div className="text-sm text-fg-tertiary">{NO_EVENTS_IN_RANGE_TEXT}</div>
        ) : (
          visibleRows.map((entry, index) => {
            // Keyed by a stable composite, not array index alone, so React does not reuse a row
            // across a reorder when a fresh events snapshot arrives.
            const key = `${entry?.device_id ?? "unknown"}:${entry?.timestamp ?? "unknown"}:${index}`;
            const device = entry?.device_id ? devices[entry.device_id] : undefined;
            return <EventRow key={key} entry={entry} device={device} />;
          })
        )}
      </div>
    </div>
  );
}
