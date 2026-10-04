// Hourly metric history for the forecast chart (D-20). The fifth lib module allowed to do
// network I/O, after runtimeConfig.ts, checkmkWrite.ts, mqttClient.ts and adminMode.ts (triageMode.ts is the sixth), and
// the only dashboard feature that reads /ch-api/.
//
// /ch-api/ is the dashboard nginx's same-origin GET path to ClickHouse's HTTP interface,
// authenticated server-side as the read-only dashboard_reader (deploy/dashboard-nginx.conf).
// Two constraints from that config: the location is exactly `/ch-api/` WITH the trailing
// slash, and the `user` / `password` query arguments are refused, so none are sent. The
// host, service and metric are bound as typed `param_*` values and never concatenated into
// the SQL (live-verified on dmc-server: `{x:UInt32}` + `param_x` passes through unchanged).
//
// The query averages with sum(value_sum)/sum(value_count) because history rows are mixed
// resolution after the 30-day TTL rollup; a plain avg(value) would weight rollup rows wrong.

export interface HistoryPoint {
  t: number; // epoch seconds
  v: number;
}

export type HistoryResult = { ok: true; points: HistoryPoint[] } | { ok: false };

export type HistoryDays = 14 | 30 | 90;

export const HISTORY_SQL =
  "SELECT toUnixTimestamp(toStartOfHour(ts)) AS t, sum(value_sum)/sum(value_count) AS v " +
  "FROM history.metrics WHERE host = {h:String} AND service = {s:String} AND metric = {m:String} " +
  "AND ts >= now() - INTERVAL {d:UInt32} DAY GROUP BY t ORDER BY t FORMAT JSON";

const TIMEOUT_MS = 10000;

// Never rejects: a failed or hung request resolves to {ok: false} so the dialog can show its
// error state while the forecast numbers still render.
export async function fetchHourlyHistory(
  host: string,
  service: string,
  metric: string,
  days: HistoryDays,
  fetchFn: typeof fetch = fetch,
): Promise<HistoryResult> {
  const params = new URLSearchParams({
    query: HISTORY_SQL,
    param_h: host,
    param_s: service,
    param_m: metric,
    param_d: String(days),
  });
  try {
    const response = await fetchFn(`/ch-api/?${params.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) {
      return { ok: false };
    }
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) {
      return { ok: false };
    }
    const data = (body as { data?: unknown }).data;
    if (!Array.isArray(data)) {
      return { ok: false };
    }
    const points: HistoryPoint[] = [];
    for (const row of data) {
      if (typeof row !== "object" || row === null) {
        continue;
      }
      const rawT = (row as { t?: unknown }).t;
      const rawV = (row as { v?: unknown }).v;
      // ClickHouse emits 64-bit integers as strings in FORMAT JSON; null (an empty group)
      // must not coerce to 0.
      if (rawT === null || rawV === null || rawT === undefined || rawV === undefined) {
        continue;
      }
      const t = Number(rawT);
      const v = Number(rawV);
      if (Number.isFinite(t) && Number.isFinite(v)) {
        points.push({ t, v });
      }
    }
    return { ok: true, points };
  } catch {
    return { ok: false };
  }
}
