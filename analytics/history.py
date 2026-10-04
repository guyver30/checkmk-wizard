"""ClickHouse HTTP access for the analytics container.

The four request helpers and `ClickHouseError` are duplicated on purpose from
scripts/mqtt_poller.py (a standalone script; the poller keeps its own copies
for `write_history`).  Reads go out as GET, which ClickHouse forces to
readonly=1 server-side; writes go out as POST.  Credentials travel in the
`X-ClickHouse-User` / `X-ClickHouse-Key` headers, never in the URL or in an
exception message.

SQL is built only from metric names validated against `METRIC_NAME_RE` (then
single-quoted) and integers from config.  Host and service names are never
interpolated into SQL; they only come back as result columns.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from analytics.config import (
    FIT_BUCKET_HOURS,
    FIT_LOOKBACK_DAYS,
    METRIC_NAME_RE,
    AnalyticsConfig,
)

ANALYTICS_TABLES = frozenset({"history.events", "history.incidents", "history.need_triage"})

_MIGRATION_HINT = (
    "run deploy/clickhouse-config/migrations/14.2-analytics.sql "
    "(see docs/DEPLOY-NEW-MACHINE.md)"
)

SeriesKey = tuple[str, str, str]  # (host, service, metric)


class ClickHouseError(RuntimeError):
    """Single normalized failure type for analytics' ClickHouse HTTP calls."""


def _clickhouse_request(
    url: str,
    *,
    user: str,
    password: str,
    timeout: float,
    data: bytes | None = None,
    method: str = "GET",
) -> bytes:
    """Send one HTTP request to ClickHouse and return the raw response body.

    Every network failure funnels through here and becomes `ClickHouseError`
    exactly once.  Auth is via headers (verified via context7,
    clickhouse.com/docs/concepts/features/interfaces/http, 2026-09-28) so the
    password never appears in the URL, and it is never put in an exception.
    """
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"X-ClickHouse-User": user, "X-ClickHouse-Key": password},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # The SQL error text is the response body; surface a bounded slice.
        try:
            body = exc.read()[:300].decode(errors="replace")
        except Exception:  # noqa: BLE001 - a synthetic HTTPError may have no fp
            body = ""
        raise ClickHouseError(
            f"ClickHouse {method} to {url} failed: HTTP {exc.code}: {body}"
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ClickHouseError(f"ClickHouse {method} to {url} failed: {exc}") from exc


def _clickhouse_insert(
    base_url: str,
    user: str,
    password: str,
    table: str,
    rows: list[dict],
    timeout: float,
) -> None:
    """POST `rows` as one `INSERT INTO {table} FORMAT JSONEachRow` batch.

    `table` must be one of `ANALYTICS_TABLES`: the name is interpolated into
    the SQL text (no parameterized identifiers over HTTP), so an unlisted
    table never reaches a request.  Empty `rows` is a no-op.
    """
    if not rows:
        return
    if table not in ANALYTICS_TABLES:
        raise ValueError(f"Refusing to insert into unlisted table {table!r}")
    try:
        body = "\n".join(json.dumps(row, allow_nan=False) for row in rows).encode("utf-8")
    except ValueError as exc:
        raise ClickHouseError(f"Refusing to insert non-finite value into {table}: {exc}") from exc
    url = f"{base_url}/?query=" + urllib.parse.quote(f"INSERT INTO {table} FORMAT JSONEachRow")
    _clickhouse_request(url, user=user, password=password, timeout=timeout, data=body, method="POST")


def _clickhouse_query(base_url: str, user: str, password: str, sql: str, timeout: float) -> list[dict]:
    """Run a read-only `sql` (GET => readonly=1) and return rows as dicts.

    ClickHouse renders 64-bit integers as JSON strings, so count columns need
    `int(...)` at the call site.
    """
    url = f"{base_url}/?query=" + urllib.parse.quote(f"{sql} FORMAT JSONEachRow")
    body = _clickhouse_request(url, user=user, password=password, timeout=timeout, method="GET")
    text = body.decode(errors="replace")
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ClickHouseError(f"Malformed JSONEachRow response for query {sql!r}: {exc}") from exc


def _clickhouse_command(base_url: str, user: str, password: str, sql: str, timeout: float) -> str:
    """POST `sql` as the body and return the decoded text response."""
    body = _clickhouse_request(
        f"{base_url}/",
        user=user,
        password=password,
        timeout=timeout,
        data=sql.encode("utf-8"),
        method="POST",
    )
    return body.decode(errors="replace")


def _query(config: AnalyticsConfig, sql: str) -> list[dict]:
    return _clickhouse_query(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        sql,
        config.clickhouse_timeout_seconds,
    )


def _metric_list(metrics) -> str:
    """Return a quoted SQL list body for allow-listed metric names.

    Raises ValueError before any request if a name fails the allow-list.
    """
    names = list(metrics)
    for name in names:
        if not isinstance(name, str) or not METRIC_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid metric name {name!r}")
    return ", ".join(f"'{name}'" for name in names)


def _num(value) -> float | None:
    return None if value is None else float(value)


def fetch_fit_buckets(
    config: AnalyticsConfig, metrics
) -> dict[SeriesKey, list[tuple[int, float]]]:
    """Bucketed averages per series over the fit lookback, sorted by time.

    The mean is `sum(value_sum) / sum(value_count)` so rows already rolled up
    by the TTL GROUP BY (history.metrics) average correctly.
    """
    metric_sql = _metric_list(metrics)
    if not metric_sql:
        return {}
    sql = (
        "SELECT host, service, metric, "
        f"toStartOfInterval(ts, INTERVAL {int(FIT_BUCKET_HOURS)} HOUR) AS bucket, "
        "toUnixTimestamp(bucket) AS t, "
        "sum(value_sum) / sum(value_count) AS v "
        "FROM history.metrics "
        f"WHERE ts >= now() - INTERVAL {int(FIT_LOOKBACK_DAYS)} DAY "
        f"AND metric IN ({metric_sql}) "
        "GROUP BY host, service, metric, bucket "
        "ORDER BY host, service, metric, bucket"
    )
    out: dict[SeriesKey, list[tuple[int, float]]] = {}
    for row in _query(config, sql):
        value = _num(row.get("v"))
        if value is None:
            continue
        key = (row["host"], row["service"], row["metric"])
        out.setdefault(key, []).append((int(row["t"]), value))
    for points in out.values():
        points.sort()
    return out


def fetch_levels(
    config: AnalyticsConfig, metrics
) -> dict[SeriesKey, tuple[float | None, float | None]]:
    """Latest (warn, crit) per series over the last 2 days; NULLs preserved."""
    metric_sql = _metric_list(metrics)
    if not metric_sql:
        return {}
    sql = (
        "SELECT host, service, metric, argMax(warn, ts) AS warn, argMax(crit, ts) AS crit "
        "FROM history.metrics "
        f"WHERE ts >= now() - INTERVAL 2 DAY AND metric IN ({metric_sql}) "
        "GROUP BY host, service, metric"
    )
    return {
        (r["host"], r["service"], r["metric"]): (_num(r.get("warn")), _num(r.get("crit")))
        for r in _query(config, sql)
    }


def fetch_recent_hourly(
    config: AnalyticsConfig, metrics, hours: int
) -> dict[SeriesKey, list[tuple[int, float]]]:
    """Hourly averages over the last `hours` hours, same shape as the fit buckets."""
    metric_sql = _metric_list(metrics)
    if not metric_sql:
        return {}
    sql = (
        "SELECT host, service, metric, "
        "toStartOfHour(ts) AS bucket, "
        "toUnixTimestamp(bucket) AS t, "
        "sum(value_sum) / sum(value_count) AS v "
        "FROM history.metrics "
        f"WHERE ts >= now() - INTERVAL {int(hours)} HOUR "
        f"AND metric IN ({metric_sql}) "
        "GROUP BY host, service, metric, bucket "
        "ORDER BY host, service, metric, bucket"
    )
    out: dict[SeriesKey, list[tuple[int, float]]] = {}
    for row in _query(config, sql):
        value = _num(row.get("v"))
        if value is None:
            continue
        out.setdefault((row["host"], row["service"], row["metric"]), []).append(
            (int(row["t"]), value)
        )
    return out


def insert_rows(config: AnalyticsConfig, table: str, rows: list[dict]) -> None:
    """Insert `rows` into one of the three analytics tables (nothing else)."""
    _clickhouse_insert(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        table,
        rows,
        config.clickhouse_timeout_seconds,
    )


def missing_tables(config: AnalyticsConfig) -> set[str]:
    """The analytics tables absent from `system.tables`.

    On any error (e.g. no permission on system.tables) all three are reported
    missing and nothing is raised; callers log `_MIGRATION_HINT`.
    """
    names = ", ".join(f"'{t.split('.', 1)[1]}'" for t in sorted(ANALYTICS_TABLES))
    sql = f"SELECT name FROM system.tables WHERE database = 'history' AND name IN ({names})"
    try:
        present = {f"history.{r['name']}" for r in _query(config, sql)}
    except ClickHouseError:
        return set(ANALYTICS_TABLES)
    return set(ANALYTICS_TABLES) - present


def fetch_open_incidents(config: AnalyticsConfig) -> list[dict]:
    """Latest version of every open incident row (FINAL: ReplacingMergeTree)."""
    rows = _query(config, "SELECT * FROM history.incidents FINAL WHERE status = 'open'")
    for row in rows:
        for column in ("duration_s", "inferred"):
            if row.get(column) is not None:
                row[column] = int(row[column])
    return rows


def fetch_recent_event_keys(config: AnalyticsConfig, days: int = 2) -> set[tuple[str, str, str, str, str]]:
    """Dedup keys (ts, device_id, event, from_state, to_state) of recent events.

    `ts` is ClickHouse's `YYYY-MM-DD HH:MM:SS` UTC text, the same shape
    inserted rows use.
    """
    sql = (
        "SELECT toString(ts) AS ts_iso, device_id, event, from_state, to_state "
        f"FROM history.events WHERE ts >= now() - INTERVAL {int(days)} DAY"
    )
    return {
        (r["ts_iso"], r["device_id"], r["event"], r["from_state"], r["to_state"])
        for r in _query(config, sql)
    }
