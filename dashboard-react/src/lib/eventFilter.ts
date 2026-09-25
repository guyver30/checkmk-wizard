// Client-side From/To range filter for the event history pane.
//
// Bounds come from <input type="datetime-local">, which has minute granularity and yields an
// offset-less "YYYY-MM-DDTHH:MM" string; Date.parse treats that as LOCAL time (ECMAScript
// date-time form without offset), matching how rows are displayed. Because of the minute
// granularity, "To 10:30" is inclusive of the whole minute (10:30:59.999), otherwise an event
// at 10:30:45 would be excluded by a bound the operator typed as 10:30.
//
// A reversed range (From later than the To minute) is not applied: the rows are returned
// unfiltered with status "reversed" so the caller can show an inline error. The function only
// uses rows.filter(), never sort/reverse: ordering is owned by EventHistory's single reversal.

import type { EventEntry } from "./types";

export type EventRange = { from: number | null; to: number | null };
export type EventFilterStatus = "unfiltered" | "filtered" | "reversed";

const MINUTE_END_MS = 59_999;

export function parseRangeBound(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function filterEventsByRange<T extends EventEntry | null | undefined>(
  rows: readonly T[],
  range: EventRange,
): { rows: T[]; status: EventFilterStatus } {
  const { from } = range;
  const to = range.to === null ? null : range.to + MINUTE_END_MS;
  if (from === null && to === null) {
    return { rows: rows.slice(), status: "unfiltered" };
  }
  if (from !== null && to !== null && from > to) {
    return { rows: rows.slice(), status: "reversed" };
  }
  const kept = rows.filter((entry) => {
    const ts = Date.parse(entry?.timestamp ?? "");
    if (Number.isNaN(ts)) {
      return false;
    }
    return (from === null || ts >= from) && (to === null || ts <= to);
  });
  return { rows: kept, status: "filtered" };
}
