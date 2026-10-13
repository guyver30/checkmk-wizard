import { describe, expect, it } from "vitest";
import {
  displayName,
  displayAddress,
  displayNameWithAddress,
  effectiveState,
  stateClass,
  stateIcon,
  isTagGroupMissing,
  formatRelativeTime,
  formatClock,
  formatDateTime,
  displayState,
  stateLabel,
  UNMANAGED_STATE,
} from "./display";

describe("displayName", () => {
  it("returns the trimmed alias when present", () => {
    expect(displayName({ alias: "  Tower B  ", id: "h1" })).toBe("Tower B");
  });

  it("falls back to id when alias is blank/whitespace-only", () => {
    expect(displayName({ alias: "   ", id: "h1" })).toBe("h1");
  });

  it("returns an empty string for a null/malformed payload", () => {
    expect(displayName(null)).toBe("");
  });
});

describe("displayAddress", () => {
  it("returns the address when the name differs from it", () => {
    expect(displayAddress({ id: "router", address: "192.168.0.1" })).toBe("192.168.0.1");
  });

  it("returns empty when the id equals the address (no alias)", () => {
    expect(displayAddress({ id: "192.168.0.5", address: "192.168.0.5" })).toBe("");
  });

  it("returns the address when an alias differs from the address", () => {
    expect(displayAddress({ id: "192.168.0.5", alias: "NAS", address: "192.168.0.5" })).toBe(
      "192.168.0.5",
    );
  });

  it("returns empty for an empty, missing, non-string address, or null payload", () => {
    expect(displayAddress({ id: "sw1", address: "" })).toBe("");
    expect(displayAddress({ id: "sw1" })).toBe("");
    expect(displayAddress({ id: "sw1", address: 42 as unknown as string })).toBe("");
    expect(displayAddress(null)).toBe("");
  });

  it("trims surrounding whitespace before comparing and returning", () => {
    expect(displayAddress({ id: "router", address: "  192.168.0.1  " })).toBe("192.168.0.1");
  });
});

describe("displayNameWithAddress", () => {
  it("appends the address in parentheses when present", () => {
    expect(displayNameWithAddress({ id: "router", address: "192.168.0.1" })).toBe(
      "router (192.168.0.1)",
    );
  });

  it("equals displayName when there is no address to show", () => {
    expect(displayNameWithAddress({ id: "sw1" })).toBe(displayName({ id: "sw1" }));
  });
});

describe("effectiveState", () => {
  it("prefers host_state_raw UNREACH over state", () => {
    expect(effectiveState({ host_state_raw: "UNREACH", state: "DOWN" })).toBe("UNREACH");
  });

  it("reads state when host_state_raw is not UNREACH", () => {
    expect(effectiveState({ state: "WARN" })).toBe("WARN");
  });

  it("returns UNKNOWN for a null/malformed payload", () => {
    expect(effectiveState(null)).toBe("UNKNOWN");
  });
});

describe("formatRelativeTime", () => {
  const nowMs = Date.parse("2026-09-21T12:00:00Z");

  it("formats under 60s as Ns ago", () => {
    expect(formatRelativeTime("2026-09-21T11:59:30Z", nowMs)).toBe("30s ago");
  });

  it("formats under 60m as Nm ago", () => {
    expect(formatRelativeTime("2026-09-21T11:55:00Z", nowMs)).toBe("5m ago");
  });

  it("formats above 60m as Nh ago", () => {
    expect(formatRelativeTime("2026-09-21T09:00:00Z", nowMs)).toBe("3h ago");
  });

  it("returns 'unknown' for an unparseable string", () => {
    expect(formatRelativeTime("not-a-date", nowMs)).toBe("unknown");
  });
});

describe("stateClass", () => {
  it("maps a known lowercase state to state-<x>", () => {
    expect(stateClass("OK")).toBe("state-ok");
  });

  it("falls back to state-unknown for an unrecognized value", () => {
    expect(stateClass("bogus")).toBe("state-unknown");
  });
});

describe("stateIcon", () => {
  it("maps every locked state to its icon class", () => {
    expect(stateIcon("OK")).toBe("icon-good-filled");
    expect(stateIcon("UNREACH")).toBe("icon-status-unavailable");
  });

  it("falls back to the UNKNOWN icon for an unrecognized state", () => {
    expect(stateIcon("bogus")).toBe("icon-question-circle-filled");
  });
});

describe("isTagGroupMissing", () => {
  it("is true only when device_type is the literal 'unknown'", () => {
    expect(isTagGroupMissing({ device_type: "unknown" })).toBe(true);
    expect(isTagGroupMissing({ device_type: "ACS" })).toBe(false);
    expect(isTagGroupMissing(null)).toBe(false);
  });
});

describe("formatClock", () => {
  it("formats a valid ISO string as HH:MM", () => {
    expect(formatClock("2026-09-21T05:07:00Z")).toMatch(/^\d{2}:\d{2}$/);
  });

  it("returns 'unknown' for an unparseable string", () => {
    expect(formatClock("not-a-date")).toBe("unknown");
  });
});

describe("formatDateTime", () => {
  it("formats a valid ISO string as local YYYY-MM-DD HH:MM:SS", () => {
    const iso = "2026-09-21T05:07:09Z";
    const d = new Date(iso);
    const p = (n: number) => String(n).padStart(2, "0");
    const expected = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    expect(formatDateTime(iso)).toBe(expected);
    expect(formatDateTime(iso)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it("returns 'unknown' for missing or unparseable input", () => {
    expect(formatDateTime(undefined)).toBe("unknown");
    expect(formatDateTime(null)).toBe("unknown");
    expect(formatDateTime("")).toBe("unknown");
    expect(formatDateTime("not-a-date")).toBe("unknown");
  });
});

describe("displayState / unmanaged", () => {
  const NOW = Date.parse("2026-10-13T12:00:00Z");
  const fresh = new Date(NOW - 5000).toISOString();
  const d = (o: Record<string, unknown>) =>
    ({ id: "sw", timestamp: fresh, staleness: 0, ...o }) as never;

  it("maps UNKNOWN and OK (faked UP) of an unmanaged switch to UNMANAGED", () => {
    expect(displayState(d({ state: "UNKNOWN" }), true, NOW)).toBe(UNMANAGED_STATE);
    expect(displayState(d({ state: "OK", host_state_raw: "UP" }), true, NOW)).toBe("UNMANAGED");
  });

  it("keeps DOWN and UNREACH", () => {
    expect(displayState(d({ state: "DOWN", host_state_raw: "DOWN" }), true, NOW)).toBe("DOWN");
    expect(displayState(d({ state: "DOWN", host_state_raw: "UNREACH" }), true, NOW)).toBe("UNREACH");
  });

  it("does not show STALE for a quiet unmanaged switch but does for a stale DOWN one", () => {
    expect(displayState(d({ state: "UNKNOWN", staleness: 9 }), true, NOW)).toBe("UNMANAGED");
    expect(displayState(d({ state: "DOWN", host_state_raw: "DOWN", staleness: 9 }), true, NOW)).toBe("STALE");
  });

  it("leaves non-unmanaged hosts exactly as before", () => {
    expect(displayState(d({ state: "UNKNOWN" }), false, NOW)).toBe("UNKNOWN");
    expect(displayState(d({ state: "OK", staleness: 9 }), false, NOW)).toBe("STALE");
  });

  it("treats a missing status of an unmanaged switch as UNMANAGED", () => {
    expect(displayState(undefined, true, NOW)).toBe("UNMANAGED");
  });

  it("labels and classifies the state", () => {
    expect(stateLabel("UNMANAGED")).toBe("Unmanaged");
    expect(stateLabel("DOWN")).toBe("DOWN");
    expect(stateClass("UNMANAGED")).toBe("state-unmanaged");
    expect(stateIcon("UNMANAGED")).not.toBe(stateIcon("UNKNOWN"));
  });
});
