import { describe, expect, it } from "vitest";
import {
  isStaleGeneratedAt,
  newestGeneratedAt,
  parseForecast,
  parseNarration,
  parseNeed,
  selectVisibleNeeds,
  worstTierByHost,
} from "./forecast";
import type { ForecastPayload, NeedPayload } from "./types";

const NOW_MS = Date.parse("2026-10-04T12:00:00Z");

function need(overrides: Partial<NeedPayload> = {}): NeedPayload {
  return {
    id: "n1",
    source: "trend",
    host: "linux1",
    service: "Filesystem /",
    metric: "fs_used_percent",
    unit: "%",
    tier: "standard",
    computed_tier: "standard",
    days_to_warn: 20,
    days_to_crit: 40,
    warn_date: null,
    crit_date: null,
    confidence: "medium",
    history_days: 14,
    value: 70,
    warn: 80,
    crit: 90,
    sustained_fraction: null,
    window_hours: null,
    since: "2026-10-01T00:00:00Z",
    narration: "",
    triage: null,
    generated_at: "2026-10-04T11:55:00Z",
    ...overrides,
  };
}

function fit(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    service: "CPU",
    metric: "util",
    unit: "%",
    status: "trending",
    history_days: 7,
    ...overrides,
  };
}

const CANCEL = {
  action: "cancel" as const,
  tier: "standard" as const,
  set_at: "t",
  computed_tier_at_set: "standard" as const,
  note: "",
  by: "me",
};

describe("parseNeed", () => {
  it("returns a typed need for a valid object", () => {
    expect(parseNeed(need())).toEqual(need());
  });

  it("returns null for non-objects, missing id/host, unknown tier or source", () => {
    expect(parseNeed(null)).toBeNull();
    expect(parseNeed([])).toBeNull();
    expect(parseNeed("x")).toBeNull();
    expect(parseNeed({ ...need(), id: undefined })).toBeNull();
    expect(parseNeed({ ...need(), host: "" })).toBeNull();
    expect(parseNeed({ ...need(), tier: "panic" })).toBeNull();
    expect(parseNeed({ ...need(), source: "magic" })).toBeNull();
  });

  it("coerces unknown optional fields to null", () => {
    const parsed = parseNeed({
      id: "n1",
      host: "h",
      tier: "urgent",
      source: "failure",
      days_to_crit: "soon",
      confidence: "certain",
      triage: { action: "explode" },
    });
    expect(parsed?.days_to_crit).toBeNull();
    expect(parsed?.confidence).toBeNull();
    expect(parsed?.triage).toBeNull();
    expect(parsed?.value).toBeNull();
  });
});

describe("parseForecast", () => {
  it("drops fits with unknown status and coerces non-finite numbers to null", () => {
    const parsed = parseForecast({
      host: "h",
      generated_at: "t",
      fits: [fit({ slope_per_day: Infinity, r2: NaN, last_value: 3 }), fit({ status: "bogus" })],
    });
    expect(parsed?.fits).toHaveLength(1);
    expect(parsed?.fits[0].slope_per_day).toBeNull();
    expect(parsed?.fits[0].r2).toBeNull();
    expect(parsed?.fits[0].last_value).toBe(3);
  });

  it("returns null when host or fits is missing", () => {
    expect(parseForecast({ fits: [] })).toBeNull();
    expect(parseForecast({ host: "h" })).toBeNull();
    expect(parseForecast(null)).toBeNull();
  });
});

describe("parseNarration", () => {
  it("requires a headline and a sentences array, dropping non-string sentences", () => {
    const parsed = parseNarration({
      id: "i",
      headline: "H",
      sentences: ["a", 2, "b"],
      tier: "urgent",
      generated_at: "t",
    });
    expect(parsed).toEqual({
      id: "i",
      headline: "H",
      sentences: ["a", "b"],
      tier: "urgent",
      generated_at: "t",
    });
    expect(parseNarration({ sentences: [] })).toBeNull();
    expect(parseNarration({ headline: "H" })).toBeNull();
  });

  it("sets tier to null unless it is a valid tier", () => {
    expect(parseNarration({ headline: "H", sentences: [], tier: "weird" })?.tier).toBeNull();
    expect(parseNarration({ headline: "H", sentences: [] })?.tier).toBeNull();
  });
});

describe("selectVisibleNeeds", () => {
  it("excludes cancelled needs", () => {
    const cancelled = need({ id: "c", triage: CANCEL });
    const result = selectVisibleNeeds({ c: cancelled, n1: need() });
    expect(result.map((n) => n.id)).toEqual(["n1"]);
  });

  it("sorts by tier, then days_to_crit ascending with null last, then host", () => {
    const record = {
      a: need({ id: "a", tier: "standard", days_to_crit: 5, host: "z" }),
      b: need({ id: "b", tier: "immediate", days_to_crit: null, host: "z" }),
      c: need({ id: "c", tier: "immediate", days_to_crit: 3, host: "z" }),
      d: need({ id: "d", tier: "urgent", days_to_crit: 9, host: "b" }),
      e: need({ id: "e", tier: "urgent", days_to_crit: 9, host: "a" }),
    };
    expect(selectVisibleNeeds(record).map((n) => n.id)).toEqual(["c", "b", "e", "d", "a"]);
  });
});

describe("worstTierByHost", () => {
  it("returns the worst effective tier per host over visible needs", () => {
    const record = {
      a: need({ id: "a", host: "h1", tier: "standard" }),
      b: need({ id: "b", host: "h1", tier: "urgent" }),
      c: need({ id: "c", host: "h2", tier: "standard" }),
      d: need({ id: "d", host: "h2", tier: "immediate", triage: CANCEL }),
    };
    expect(worstTierByHost(record)).toEqual({ h1: "urgent", h2: "standard" });
  });
});

describe("newestGeneratedAt / isStaleGeneratedAt", () => {
  it("returns the max generated_at across needs and forecasts, or null", () => {
    expect(newestGeneratedAt({}, {})).toBeNull();
    const forecast: ForecastPayload = { host: "h", generated_at: "2026-10-04T11:59:00Z", fits: [] };
    const result = newestGeneratedAt({ n1: need() }, { h: forecast });
    expect(result).toBe(Date.parse("2026-10-04T11:59:00Z"));
  });

  it("is stale only after 45 minutes", () => {
    expect(isStaleGeneratedAt(NOW_MS - 44 * 60 * 1000, NOW_MS)).toBe(false);
    expect(isStaleGeneratedAt(NOW_MS - 46 * 60 * 1000, NOW_MS)).toBe(true);
  });
});
