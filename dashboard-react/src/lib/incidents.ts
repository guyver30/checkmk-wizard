// Incident criticality ranking, payload normalization, D-12 ordering and host->incident
// lookup. Mirrors grouping.ts's "one source of truth per derived ordering" convention
// (14-RESEARCH.md Pitfall 4) rather than re-deriving a comparator ad hoc at each call site.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import type { IncidentPayload } from "./types";

// Mirrors CRITICALITY_TIERS in scripts/mqtt_poller.py -- two languages, kept in step by
// hand, no shared source (same convention as grouping.ts SEVERITY_RANK).
export const CRITICALITY_TIERS = ["low", "medium", "high", "critical"] as const;
export type CriticalityTier = (typeof CRITICALITY_TIERS)[number];

export const CRITICALITY_RANK: Record<CriticalityTier, number> = {
  low: 0,
  medium: 1,
  high: 2,
  critical: 3,
};

export function isCriticalityTier(value: unknown): value is CriticalityTier {
  return typeof value === "string" && (CRITICALITY_TIERS as readonly string[]).includes(value);
}

export function criticalityRank(value: unknown): number {
  return isCriticalityTier(value) ? CRITICALITY_RANK[value] : 0;
}

export interface Incident {
  id: string;
  root: string;
  rootState: string;
  inferred: boolean;
  confirmedDown: string[];
  notObservable: string[];
  dependents: string[];
  worstCriticality: CriticalityTier;
  since: string | null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Non-array inputs become []; non-string entries are dropped rather than coerced, since a
// malformed host id string is worse than a missing one.
function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string");
}

// Runtime guard for untrusted IncidentPayload JSON crossing the MQTT trust boundary.
// Returns null when the payload lacks the two fields an incident cannot exist without
// (id, root); every other field degrades to a safe default instead of rejecting the whole
// incident.
export function normalizeIncident(raw: unknown): Incident | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  const payload = raw as IncidentPayload;
  const id = typeof payload.id === "string" && payload.id.length > 0 ? payload.id : null;
  if (!id) {
    return null;
  }
  const root = typeof payload.root === "string" && payload.root.length > 0 ? payload.root : null;
  if (!root) {
    return null;
  }
  return {
    id,
    root,
    rootState: typeof payload.root_state === "string" ? payload.root_state : "",
    inferred: typeof payload.inferred === "boolean" ? payload.inferred : false,
    confirmedDown: toStringList(payload.confirmed_down),
    notObservable: toStringList(payload.not_observable),
    dependents: toStringList(payload.dependents),
    worstCriticality: isCriticalityTier(payload.worst_criticality)
      ? payload.worst_criticality
      : "low",
    since: typeof payload.since === "string" ? payload.since : null,
  };
}

// D-12 ordering: worst criticality tier descending, then duration descending (the older
// (longer-open) `since` sorts first within a tier), null `since` last within its tier, ties
// broken by id ascending. Returns a new array -- callers hold the input array too (e.g. the
// raw record iteration order in selectOpenIncidents).
export function sortIncidents(incidents: Incident[]): Incident[] {
  return [...incidents].sort((a, b) => {
    const rankDiff = criticalityRank(b.worstCriticality) - criticalityRank(a.worstCriticality);
    if (rankDiff !== 0) {
      return rankDiff;
    }
    const aSince = a.since ? Date.parse(a.since) : NaN;
    const bSince = b.since ? Date.parse(b.since) : NaN;
    const aValid = !Number.isNaN(aSince);
    const bValid = !Number.isNaN(bSince);
    if (aValid && bValid) {
      if (aSince !== bSince) {
        return aSince - bSince;
      }
    } else if (aValid !== bValid) {
      return aValid ? -1 : 1; // a real `since` sorts before a null one, same tier
    }
    return a.id.localeCompare(b.id);
  });
}

export function selectOpenIncidents(record: Record<string, IncidentPayload>): Incident[] {
  if (!record || typeof record !== "object") {
    return [];
  }
  const incidents: Incident[] = [];
  for (const raw of Object.values(record)) {
    const normalized = normalizeIncident(raw);
    if (normalized) {
      incidents.push(normalized);
    }
  }
  return sortIncidents(incidents);
}

export type IncidentRole = "root" | "consequence";

export interface IncidentMembership {
  incidentId: string;
  role: IncidentRole;
  inferred: boolean;
}

export type IncidentLookup = Map<string, IncidentMembership>;

// Every root and consequence (confirmed_down + not_observable) host maps to its incident;
// dependents are deliberately excluded (D-15: a dependent gets no tree/map marker of its
// own, only a line on the incident card). Callers should pass an already-ordered incident
// list (e.g. selectOpenIncidents's output) so "first incident wins" resolves ties the same
// way the card list itself is ordered.
export function buildIncidentLookup(incidents: Incident[]): IncidentLookup {
  const lookup: IncidentLookup = new Map();
  for (const incident of incidents) {
    if (!lookup.has(incident.root)) {
      lookup.set(incident.root, {
        incidentId: incident.id,
        role: "root",
        inferred: incident.inferred,
      });
    }
    for (const hostId of [...incident.confirmedDown, ...incident.notObservable]) {
      if (!lookup.has(hostId)) {
        lookup.set(hostId, {
          incidentId: incident.id,
          role: "consequence",
          inferred: incident.inferred,
        });
      }
    }
  }
  return lookup;
}

// Compact duration string for an incident card's root line ("{rootLabel} — {duration}").
// Ticks client-side off the app's existing useNowTick hook -- this function itself is
// stateless and takes `nowMs` as an argument, publishing no timer of its own
// (14-RESEARCH.md's Don't-Hand-Roll table).
export function formatIncidentDuration(since: string | null, nowMs: number): string {
  if (typeof since !== "string") {
    return "duration unknown";
  }
  const sinceMs = Date.parse(since);
  if (Number.isNaN(sinceMs)) {
    return "duration unknown";
  }
  const diffSeconds = Math.max(0, Math.round((nowMs - sinceMs) / 1000));
  if (diffSeconds < 60) {
    return `${diffSeconds} s`;
  }
  if (diffSeconds < 3600) {
    const minutes = Math.floor(diffSeconds / 60);
    return `${minutes} min`;
  }
  if (diffSeconds < 86400) {
    const hours = Math.floor(diffSeconds / 3600);
    const minutes = Math.floor((diffSeconds - hours * 3600) / 60);
    return `${hours} h ${minutes} min`;
  }
  const days = Math.floor(diffSeconds / 86400);
  const hours = Math.floor((diffSeconds - days * 86400) / 3600);
  return `${days} d ${hours} h`;
}

// D-04's locked wording constraint: never assert that a device has stopped functioning
// from UNREACH evidence alone. "{N} confirmed down · {M} not observable"; a zero count
// drops its own clause entirely rather than rendering "0 confirmed down".
export function consequenceSummary(incident: Incident): string {
  const confirmedDownCount = incident.confirmedDown.length;
  const notObservableCount = incident.notObservable.length;
  if (confirmedDownCount > 0 && notObservableCount > 0) {
    return `${confirmedDownCount} confirmed down · ${notObservableCount} not observable`;
  }
  if (confirmedDownCount > 0) {
    return `${confirmedDownCount} confirmed down`;
  }
  if (notObservableCount > 0) {
    return `${notObservableCount} not observable`;
  }
  return "";
}

// UI-SPEC's Incident Card List status rule -- the one place alarm weight could leak from
// pure UNREACH/inferred evidence into a "danger" render. An incident made entirely of
// not-observable hosts (including every purely-inferred case) must never outrank a
// confirmed-down incident visually.
export function incidentStatus(incident: Incident): "danger" | "warning" {
  if (incident.confirmedDown.length > 0) {
    return "danger";
  }
  if (incident.rootState === "DOWN" && !incident.inferred) {
    return "danger";
  }
  return "warning";
}
