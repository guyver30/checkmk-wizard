import { describe, expect, it } from "vitest";
import {
  CRITICALITY_RANK,
  CRITICALITY_TIERS,
  buildIncidentLookup,
  consequenceSummary,
  criticalityRank,
  formatIncidentDuration,
  incidentStatus,
  normalizeIncident,
  selectOpenIncidents,
  sortIncidents,
  type Incident,
} from "./incidents";
import type { IncidentPayload } from "./types";

describe("CRITICALITY_TIERS / CRITICALITY_RANK", () => {
  it("lists the four tiers in ascending order", () => {
    expect(CRITICALITY_TIERS).toEqual(["low", "medium", "high", "critical"]);
  });

  it("ranks the four tiers in ascending order", () => {
    expect(CRITICALITY_RANK).toEqual({ low: 0, medium: 1, high: 2, critical: 3 });
  });

  it("criticalityRank treats an unknown value as the lowest tier", () => {
    expect(criticalityRank("bogus")).toBe(0);
    expect(criticalityRank(undefined)).toBe(0);
  });

  it("never produces the phrase 'not operating' in rendered copy (D-04)", () => {
    const incident = normalizeIncident({
      id: "incident-a",
      root: "a",
      root_state: "UNREACH",
      inferred: true,
      confirmed_down: [],
      not_observable: ["b", "c"],
      dependents: [],
      worst_criticality: "low",
      since: null,
    })!;
    expect(consequenceSummary(incident)).not.toContain("operating");
  });
});

describe("normalizeIncident", () => {
  it("returns an Incident with camelCase fields and the same values for a well-formed payload", () => {
    const raw: IncidentPayload = {
      id: "incident-a",
      root: "a",
      root_state: "DOWN",
      inferred: false,
      confirmed_down: ["b"],
      not_observable: ["c"],
      dependents: [],
      worst_criticality: "high",
      since: "2026-09-26T10:00:00+00:00",
    };
    expect(normalizeIncident(raw)).toEqual({
      id: "incident-a",
      root: "a",
      rootState: "DOWN",
      inferred: false,
      confirmedDown: ["b"],
      notObservable: ["c"],
      dependents: [],
      worstCriticality: "high",
      since: "2026-09-26T10:00:00+00:00",
    });
  });

  it("returns null for a non-object payload", () => {
    expect(normalizeIncident("not-an-object")).toBeNull();
    expect(normalizeIncident(null)).toBeNull();
    expect(normalizeIncident([1, 2, 3])).toBeNull();
  });

  it("returns null when id is missing or empty", () => {
    expect(normalizeIncident({ root: "a" })).toBeNull();
    expect(normalizeIncident({ id: "", root: "a" })).toBeNull();
  });

  it("returns null when root is missing or empty", () => {
    expect(normalizeIncident({ id: "incident-a" })).toBeNull();
    expect(normalizeIncident({ id: "incident-a", root: "" })).toBeNull();
  });

  it("defaults non-array list fields to []", () => {
    const result = normalizeIncident({
      id: "incident-a",
      root: "a",
      confirmed_down: "not-an-array",
      not_observable: null,
      dependents: 5,
    })!;
    expect(result.confirmedDown).toEqual([]);
    expect(result.notObservable).toEqual([]);
    expect(result.dependents).toEqual([]);
  });

  it("drops non-string entries from list fields", () => {
    const result = normalizeIncident({
      id: "incident-a",
      root: "a",
      confirmed_down: ["b", 1, null, "c", {}],
    })!;
    expect(result.confirmedDown).toEqual(["b", "c"]);
  });

  it("clamps an unknown worst_criticality to 'low'", () => {
    const result = normalizeIncident({ id: "incident-a", root: "a", worst_criticality: "extreme" })!;
    expect(result.worstCriticality).toBe("low");
  });

  it("defaults a non-string since to null", () => {
    const result = normalizeIncident({ id: "incident-a", root: "a", since: 12345 })!;
    expect(result.since).toBeNull();
  });

  it("defaults a non-boolean inferred to false", () => {
    const result = normalizeIncident({ id: "incident-a", root: "a", inferred: "yes" })!;
    expect(result.inferred).toBe(false);
  });
});

function makeIncident(overrides: Partial<Incident>): Incident {
  return {
    id: "incident-x",
    root: "x",
    rootState: "DOWN",
    inferred: false,
    confirmedDown: [],
    notObservable: [],
    dependents: [],
    worstCriticality: "low",
    since: null,
    ...overrides,
  };
}

describe("sortIncidents", () => {
  it("orders by worst criticality descending, then duration (oldest since first) within a tier", () => {
    const lowOld = makeIncident({ id: "incident-low-old", worstCriticality: "low", since: "2026-09-26T09:00:00Z" });
    const criticalNew = makeIncident({
      id: "incident-critical-new",
      worstCriticality: "critical",
      since: "2026-09-26T09:59:00Z",
    });
    const criticalOld = makeIncident({
      id: "incident-critical-old",
      worstCriticality: "critical",
      since: "2026-09-26T09:00:00Z",
    });
    expect(sortIncidents([lowOld, criticalNew, criticalOld])).toEqual([
      criticalOld,
      criticalNew,
      lowOld,
    ]);
  });

  it("sorts a null since after any real since within the same tier", () => {
    const withSince = makeIncident({ id: "incident-a", worstCriticality: "high", since: "2026-09-26T09:00:00Z" });
    const withoutSince = makeIncident({ id: "incident-b", worstCriticality: "high", since: null });
    expect(sortIncidents([withoutSince, withSince])).toEqual([withSince, withoutSince]);
  });

  it("breaks ties by id ascending", () => {
    const b = makeIncident({ id: "incident-b", worstCriticality: "medium", since: null });
    const a = makeIncident({ id: "incident-a", worstCriticality: "medium", since: null });
    expect(sortIncidents([b, a])).toEqual([a, b]);
  });
});

describe("selectOpenIncidents", () => {
  it("normalizes every record value, drops nulls, and returns them sorted", () => {
    const record: Record<string, IncidentPayload> = {
      "incident-a": { id: "incident-a", root: "a", worst_criticality: "low" },
      "incident-b": { id: "incident-b", root: "b", worst_criticality: "critical" },
      "incident-bad": "not-an-object" as unknown as IncidentPayload,
    };
    const result = selectOpenIncidents(record);
    expect(result.map((incident) => incident.id)).toEqual(["incident-b", "incident-a"]);
  });
});

describe("buildIncidentLookup", () => {
  it("maps root to role 'root' and every confirmed_down/not_observable host to 'consequence'", () => {
    const incident = makeIncident({
      id: "incident-a",
      root: "a",
      inferred: true,
      confirmedDown: ["b"],
      notObservable: ["c"],
      dependents: ["d"],
    });
    const lookup = buildIncidentLookup([incident]);
    expect(lookup.get("a")).toEqual({ incidentId: "incident-a", role: "root", inferred: true });
    expect(lookup.get("b")).toEqual({ incidentId: "incident-a", role: "consequence", inferred: true });
    expect(lookup.get("c")).toEqual({ incidentId: "incident-a", role: "consequence", inferred: true });
  });

  it("does not include dependents in the lookup", () => {
    const incident = makeIncident({ id: "incident-a", root: "a", dependents: ["d"] });
    const lookup = buildIncidentLookup([incident]);
    expect(lookup.has("d")).toBe(false);
  });

  it("lets the first incident in the given order win when a host appears twice", () => {
    const first = makeIncident({ id: "incident-first", root: "root1", confirmedDown: ["shared"] });
    const second = makeIncident({ id: "incident-second", root: "root2", confirmedDown: ["shared"] });
    const lookup = buildIncidentLookup([first, second]);
    expect(lookup.get("shared")).toEqual({
      incidentId: "incident-first",
      role: "consequence",
      inferred: false,
    });
  });
});

describe("formatIncidentDuration", () => {
  it("formats a 12 minute 30 second gap as '12 min'", () => {
    expect(
      formatIncidentDuration("2026-09-26T10:00:00Z", Date.parse("2026-09-26T10:12:30Z")),
    ).toBe("12 min");
  });

  it("formats a 45 second gap as '45 s'", () => {
    expect(
      formatIncidentDuration("2026-09-26T10:00:00Z", Date.parse("2026-09-26T10:00:45Z")),
    ).toBe("45 s");
  });

  it("formats a 3h5min gap as '3 h 5 min'", () => {
    expect(
      formatIncidentDuration("2026-09-26T10:00:00Z", Date.parse("2026-09-26T13:05:00Z")),
    ).toBe("3 h 5 min");
  });

  it("formats a 2d4h gap as '2 d 4 h'", () => {
    expect(
      formatIncidentDuration("2026-09-26T10:00:00Z", Date.parse("2026-09-28T14:00:00Z")),
    ).toBe("2 d 4 h");
  });

  it("returns 'duration unknown' for a null or unparseable since", () => {
    expect(formatIncidentDuration(null, Date.now())).toBe("duration unknown");
    expect(formatIncidentDuration("not-a-date", Date.now())).toBe("duration unknown");
  });

  it("clamps a future since to '0 s'", () => {
    expect(
      formatIncidentDuration("2026-09-26T10:05:00Z", Date.parse("2026-09-26T10:00:00Z")),
    ).toBe("0 s");
  });
});

describe("consequenceSummary", () => {
  it("renders both counts joined by a middle dot when both are non-zero", () => {
    const incident = makeIncident({ confirmedDown: ["a", "b"], notObservable: ["c", "d", "e", "f"] });
    expect(consequenceSummary(incident)).toBe("2 confirmed down · 4 not observable");
  });

  it("renders only not-observable when confirmed down is zero", () => {
    const incident = makeIncident({ confirmedDown: [], notObservable: ["a", "b", "c", "d"] });
    expect(consequenceSummary(incident)).toBe("4 not observable");
  });

  it("renders only confirmed down when not-observable is zero", () => {
    const incident = makeIncident({ confirmedDown: ["a", "b"], notObservable: [] });
    expect(consequenceSummary(incident)).toBe("2 confirmed down");
  });

  it("renders an empty string for a root-only incident (both zero)", () => {
    const incident = makeIncident({ confirmedDown: [], notObservable: [] });
    expect(consequenceSummary(incident)).toBe("");
  });
});

describe("incidentStatus", () => {
  it("is 'danger' when there is any confirmed-down consequence", () => {
    const incident = makeIncident({ confirmedDown: ["a"], rootState: "UNREACH", inferred: true });
    expect(incidentStatus(incident)).toBe("danger");
  });

  it("is 'danger' when the root itself is DOWN and not inferred", () => {
    const incident = makeIncident({ confirmedDown: [], rootState: "DOWN", inferred: false });
    expect(incidentStatus(incident)).toBe("danger");
  });

  it("is 'warning' for a purely-inferred, all-not-observable incident", () => {
    const incident = makeIncident({ confirmedDown: [], rootState: "DOWN", inferred: true });
    expect(incidentStatus(incident)).toBe("warning");
  });

  it("is 'warning' when the root is only UNREACH with no confirmed-down consequence", () => {
    const incident = makeIncident({ confirmedDown: [], rootState: "UNREACH", inferred: false });
    expect(incidentStatus(incident)).toBe("warning");
  });
});
