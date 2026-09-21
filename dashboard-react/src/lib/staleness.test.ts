import { describe, expect, it } from "vitest";
import { isDeviceStale, isPollerStale, pollerOfflineSince } from "./staleness";
import { STALENESS_FACTOR, POLL_INTERVAL_SECONDS } from "./config";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");

describe("isDeviceStale", () => {
  it("takes the Checkmk-supplied staleness value in preference to the timestamp", () => {
    expect(isDeviceStale({ staleness: STALENESS_FACTOR }, NOW_MS)).toBe(true);
    expect(isDeviceStale({ staleness: 1 }, NOW_MS)).toBe(false);
  });

  it("falls back to timestamp age at STALENESS_FACTOR x POLL_INTERVAL_SECONDS", () => {
    const staleTimestamp = new Date(NOW_MS - 200 * 1000).toISOString();
    const freshTimestamp = new Date(NOW_MS - 10 * 1000).toISOString();
    expect(isDeviceStale({ timestamp: staleTimestamp }, NOW_MS)).toBe(true);
    expect(isDeviceStale({ timestamp: freshTimestamp }, NOW_MS)).toBe(false);
    // Sanity check the fixture actually straddles the factor boundary.
    expect(200).toBeGreaterThanOrEqual(STALENESS_FACTOR * POLL_INTERVAL_SECONDS);
    expect(10).toBeLessThan(STALENESS_FACTOR * POLL_INTERVAL_SECONDS);
  });

  it("treats a missing/unparseable timestamp as stale", () => {
    expect(isDeviceStale({}, NOW_MS)).toBe(true);
    expect(isDeviceStale({ timestamp: "not-a-date" }, NOW_MS)).toBe(true);
  });

  it("treats a null/malformed payload as stale", () => {
    expect(isDeviceStale(null, NOW_MS)).toBe(true);
  });
});

describe("isPollerStale", () => {
  it("is true for a null payload and for an explicit offline status", () => {
    expect(isPollerStale(null, NOW_MS)).toBe(true);
    expect(isPollerStale({ status: "offline" }, NOW_MS)).toBe(true);
  });

  it("is false for an online status with no last_poll (a birth message)", () => {
    expect(isPollerStale({ status: "online" }, NOW_MS)).toBe(false);
  });
});

describe("pollerOfflineSince", () => {
  it("builds a Date from the fallback when the payload has neither last_poll nor since", () => {
    const fallback = "2026-09-21T10:00:00Z";
    const result = pollerOfflineSince({ status: "offline" }, fallback);
    expect(result).toEqual(new Date(Date.parse(fallback)));
  });

  it("returns null for a null/malformed payload", () => {
    expect(pollerOfflineSince(null)).toBeNull();
  });
});
