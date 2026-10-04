// Payload parsing and selection for the failure-prediction needs, per-host forecasts and
// incident narrations. Mirrors incidents.ts's convention: untrusted retained JSON is
// validated here, and every derived ordering has one source of truth.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import type {
  FitPayload,
  ForecastConfidence,
  ForecastPayload,
  NarrationPayload,
  NeedPayload,
  NeedSource,
  NeedTier,
  NeedTriage,
} from "./types";

// Two languages, kept in step by hand with the analytics service (same convention as
// incidents.ts CRITICALITY_TIERS).
export const NEED_TIERS = ["immediate", "urgent", "standard"] as const;

const NEED_TIER_RANK: Record<NeedTier, number> = { immediate: 0, urgent: 1, standard: 2 };

const NEED_SOURCES: readonly string[] = ["failure", "trend", "sustained"];
const FIT_STATUSES: readonly string[] = ["trending", "stable", "no_clear_trend"];
const CONFIDENCES: readonly string[] = ["low", "medium", "high"];
const TRIAGE_ACTIONS: readonly string[] = ["downgrade", "upgrade", "cancel"];

// Three missed 15-minute analytics cycles.
export const STALE_AFTER_MS = 45 * 60 * 1000;

export function isNeedTier(value: unknown): value is NeedTier {
  return typeof value === "string" && (NEED_TIERS as readonly string[]).includes(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function confidence(value: unknown): ForecastConfidence | null {
  return typeof value === "string" && CONFIDENCES.includes(value)
    ? (value as ForecastConfidence)
    : null;
}

function parseTriage(raw: unknown): NeedTriage | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.action !== "string" || !TRIAGE_ACTIONS.includes(raw.action)) {
    return null;
  }
  if (!isNeedTier(raw.tier)) {
    return null;
  }
  return {
    action: raw.action as NeedTriage["action"],
    tier: raw.tier,
    set_at: str(raw.set_at),
    computed_tier_at_set: isNeedTier(raw.computed_tier_at_set)
      ? raw.computed_tier_at_set
      : raw.tier,
    note: str(raw.note),
    by: str(raw.by),
  };
}

// Null when the payload lacks what a need cannot exist without (id, host, valid tier and
// source); every other field degrades to null / "" rather than rejecting the whole need.
export function parseNeed(raw: unknown): NeedPayload | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.id !== "string" || raw.id.length === 0) {
    return null;
  }
  if (typeof raw.host !== "string" || raw.host.length === 0) {
    return null;
  }
  if (!isNeedTier(raw.tier)) {
    return null;
  }
  if (typeof raw.source !== "string" || !NEED_SOURCES.includes(raw.source)) {
    return null;
  }
  return {
    id: raw.id,
    source: raw.source as NeedSource,
    host: raw.host,
    service: str(raw.service),
    metric: str(raw.metric),
    unit: str(raw.unit),
    tier: raw.tier,
    computed_tier: isNeedTier(raw.computed_tier) ? raw.computed_tier : raw.tier,
    days_to_warn: numOrNull(raw.days_to_warn),
    days_to_crit: numOrNull(raw.days_to_crit),
    warn_date: strOrNull(raw.warn_date),
    crit_date: strOrNull(raw.crit_date),
    confidence: confidence(raw.confidence),
    history_days: numOrNull(raw.history_days),
    value: numOrNull(raw.value),
    warn: numOrNull(raw.warn),
    crit: numOrNull(raw.crit),
    sustained_fraction: numOrNull(raw.sustained_fraction),
    window_hours: numOrNull(raw.window_hours),
    since: str(raw.since),
    narration: str(raw.narration),
    triage: parseTriage(raw.triage),
    generated_at: str(raw.generated_at),
  };
}

function parseFit(raw: unknown): FitPayload | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.status !== "string" || !FIT_STATUSES.includes(raw.status)) {
    return null;
  }
  return {
    service: str(raw.service),
    metric: str(raw.metric),
    unit: str(raw.unit),
    status: raw.status as FitPayload["status"],
    slope_per_day: numOrNull(raw.slope_per_day),
    value_at_end: numOrNull(raw.value_at_end),
    fit_start_ts: numOrNull(raw.fit_start_ts),
    fit_end_ts: numOrNull(raw.fit_end_ts),
    r2: numOrNull(raw.r2),
    history_days: numOrNull(raw.history_days) ?? 0,
    confidence: confidence(raw.confidence),
    last_value: numOrNull(raw.last_value),
    warn: numOrNull(raw.warn),
    crit: numOrNull(raw.crit),
    warn_ts: numOrNull(raw.warn_ts),
    crit_ts: numOrNull(raw.crit_ts),
    warn_date: strOrNull(raw.warn_date),
    crit_date: strOrNull(raw.crit_date),
    days_to_warn: numOrNull(raw.days_to_warn),
    days_to_crit: numOrNull(raw.days_to_crit),
  };
}

export function parseForecast(raw: unknown): ForecastPayload | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.host !== "string" || raw.host.length === 0 || !Array.isArray(raw.fits)) {
    return null;
  }
  const fits = raw.fits.map(parseFit).filter((fit): fit is FitPayload => fit !== null);
  return { host: raw.host, generated_at: str(raw.generated_at), fits };
}

export function parseNarration(raw: unknown): NarrationPayload | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.headline !== "string" || !Array.isArray(raw.sentences)) {
    return null;
  }
  return {
    id: str(raw.id),
    headline: raw.headline,
    sentences: raw.sentences.filter((s): s is string => typeof s === "string"),
    tier: isNeedTier(raw.tier) ? raw.tier : null,
    generated_at: str(raw.generated_at),
  };
}

function compareNeeds(a: NeedPayload, b: NeedPayload): number {
  const tierDiff = NEED_TIER_RANK[a.tier] - NEED_TIER_RANK[b.tier];
  if (tierDiff !== 0) {
    return tierDiff;
  }
  const aDays = a.days_to_crit;
  const bDays = b.days_to_crit;
  if (aDays !== bDays) {
    if (aDays === null) {
      return 1;
    }
    if (bDays === null) {
      return -1;
    }
    return aDays - bDays;
  }
  return a.host.localeCompare(b.host);
}

// Needs pane list: cancelled needs (operator triage) are hidden, the rest sorted tier,
// then days_to_crit ascending (null last), then host. Returns a new array.
export function selectVisibleNeeds(record: Record<string, NeedPayload>): NeedPayload[] {
  if (!record || typeof record !== "object") {
    return [];
  }
  return Object.values(record)
    .filter((need) => need.triage?.action !== "cancel")
    .sort(compareNeeds);
}

// host -> worst effective tier over the visible needs, for topology / grouping markers.
export function worstTierByHost(record: Record<string, NeedPayload>): Record<string, NeedTier> {
  const worst: Record<string, NeedTier> = {};
  for (const need of selectVisibleNeeds(record)) {
    const current = worst[need.host];
    if (!current || NEED_TIER_RANK[need.tier] < NEED_TIER_RANK[current]) {
      worst[need.host] = need.tier;
    }
  }
  return worst;
}

// Newest generated_at over needs and forecasts, in epoch ms; null when there is none.
export function newestGeneratedAt(
  needs: Record<string, NeedPayload>,
  forecasts: Record<string, ForecastPayload>,
): number | null {
  let newest: number | null = null;
  const consider = (value: string) => {
    const ms = Date.parse(value);
    if (!Number.isNaN(ms) && (newest === null || ms > newest)) {
      newest = ms;
    }
  };
  for (const need of Object.values(needs ?? {})) {
    consider(need.generated_at);
  }
  for (const forecast of Object.values(forecasts ?? {})) {
    consider(forecast.generated_at);
  }
  return newest;
}

export function isStaleGeneratedAt(generatedAtMs: number, nowMs: number): boolean {
  return nowMs - generatedAtMs > STALE_AFTER_MS;
}
