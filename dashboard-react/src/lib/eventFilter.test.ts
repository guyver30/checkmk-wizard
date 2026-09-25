import { describe, expect, it } from "vitest";
import { filterEventsByRange, parseRangeBound } from "./eventFilter";
import type { EventEntry } from "./types";

// Local-time datetime-local string ("YYYY-MM-DDTHH:MM") for a given Date, built from local
// getters so the tests pass in any timezone.
function local(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

const T = (h: number, m: number, s = 0) => new Date(2026, 8, 24, h, m, s);
const ev = (id: string, d: Date): EventEntry => ({ device_id: id, timestamp: d.toISOString() });

// Newest-first, as EventHistory hands them over.
const rows: EventEntry[] = [ev("d", T(12, 0)), ev("c", T(10, 30, 45)), ev("b", T(10, 30)), ev("a", T(9, 0))];
const ids = (r: readonly (EventEntry | null | undefined)[]) => r.map((e) => e?.device_id);

describe("parseRangeBound", () => {
  it("returns null for empty/undefined/garbage", () => {
    expect(parseRangeBound("")).toBeNull();
    expect(parseRangeBound(undefined)).toBeNull();
    expect(parseRangeBound("garbage")).toBeNull();
  });

  it("parses an offset-less datetime-local string as local time", () => {
    expect(parseRangeBound("2026-09-24T10:30")).toBe(T(10, 30).getTime());
  });
});

describe("filterEventsByRange", () => {
  it("returns rows unchanged with status unfiltered when both bounds are null", () => {
    const out = filterEventsByRange(rows, { from: null, to: null });
    expect(out.status).toBe("unfiltered");
    expect(ids(out.rows)).toEqual(["d", "c", "b", "a"]);
  });

  it("From-only keeps entries at or after From", () => {
    const out = filterEventsByRange(rows, { from: parseRangeBound(local(T(10, 30))), to: null });
    expect(out.status).toBe("filtered");
    expect(ids(out.rows)).toEqual(["d", "c", "b"]);
  });

  it("To-only includes the whole To minute", () => {
    const out = filterEventsByRange(rows, { from: null, to: parseRangeBound(local(T(10, 30))) });
    expect(ids(out.rows)).toEqual(["c", "b", "a"]);
  });

  it("applies both bounds inclusively", () => {
    const out = filterEventsByRange(rows, {
      from: parseRangeBound(local(T(10, 30))),
      to: parseRangeBound(local(T(10, 30))),
    });
    expect(ids(out.rows)).toEqual(["c", "b"]);
  });

  it("excludes null and unparseable-timestamp entries when a bound is active", () => {
    const mixed = [null, { device_id: "x" }, { device_id: "y", timestamp: "nope" }, ev("b", T(10, 30))];
    const out = filterEventsByRange(mixed, { from: parseRangeBound(local(T(9, 0))), to: null });
    expect(ids(out.rows)).toEqual(["b"]);
  });

  it("returns rows unfiltered with status reversed when From is after To", () => {
    const out = filterEventsByRange(rows, {
      from: parseRangeBound(local(T(11, 0))),
      to: parseRangeBound(local(T(10, 0))),
    });
    expect(out.status).toBe("reversed");
    expect(ids(out.rows)).toEqual(["d", "c", "b", "a"]);
  });

  it("reports filtered even when the range yields zero rows", () => {
    const out = filterEventsByRange(rows, { from: parseRangeBound(local(T(20, 0))), to: null });
    expect(out.status).toBe("filtered");
    expect(out.rows).toEqual([]);
  });

  it("does not mutate a frozen input", () => {
    const frozen = Object.freeze([...rows]);
    expect(() => filterEventsByRange(frozen, { from: parseRangeBound(local(T(10, 0))), to: null })).not.toThrow();
  });
});
