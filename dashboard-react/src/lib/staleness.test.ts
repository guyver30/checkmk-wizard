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

describe("isDeviceStale with heartbeat_s", () => {
  const ago = (s: number) => new Date(NOW_MS - s * 1000).toISOString();

  it("is not stale 200 s old with heartbeat_s 300 and null staleness", () => {
    expect(isDeviceStale({ staleness: null, heartbeat_s: 300, timestamp: ago(200) }, NOW_MS)).toBe(false);
  });

  it("is stale 900 s old with heartbeat_s 300", () => {
    expect(isDeviceStale({ staleness: null, heartbeat_s: 300, timestamp: ago(900) }, NOW_MS)).toBe(true);
  });

  it("keeps 3 x 15 s when heartbeat_s is absent", () => {
    expect(isDeviceStale({ staleness: null, timestamp: ago(50) }, NOW_MS)).toBe(true);
  });

  it("keeps 3 x 15 s when heartbeat_s is 0", () => {
    expect(isDeviceStale({ staleness: null, heartbeat_s: 0, timestamp: ago(50) }, NOW_MS)).toBe(true);
  });

  it.each([-5, Number.NaN, Number.POSITIVE_INFINITY, "300"])(
    "ignores invalid heartbeat_s %j",
    (bad) => {
      const payload = { staleness: null, heartbeat_s: bad, timestamp: ago(50) } as unknown as Parameters<
        typeof isDeviceStale
      >[0];
      expect(isDeviceStale(payload, NOW_MS)).toBe(true);
    },
  );

  it("lets a Checkmk staleness >= 3 win over a fresh timestamp and heartbeat_s", () => {
    expect(isDeviceStale({ staleness: 3.2, heartbeat_s: 300, timestamp: ago(1) }, NOW_MS)).toBe(true);
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
