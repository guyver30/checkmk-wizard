import { describe, expect, it } from "vitest";
import {
  displayName,
  effectiveState,
  stateClass,
  stateIcon,
  isTagGroupMissing,
  formatRelativeTime,
  formatClock,
  formatDateTime,
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
