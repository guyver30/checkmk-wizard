"""Daily availability rollup: JSON + Parquet objects in MinIO (phase 14.2 D-04).

Moved from the poller unchanged in behaviour.  Every object write is
never-overwrite (14.1 D-44/D-52), so running alongside the poller's own copy
during the transition is harmless: whichever writer gets there first wins and
the other sees both objects present and skips.  The scheduler auto-backfills
28 days, so a failed first run self-heals once fixed.

ClickHouse access uses the `analytics_writer` user, which needs GRANT S3 (for
the Parquet export through the `s3` table function) and CREATE TEMPORARY TABLE
(plan 02's migration).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import urllib.parse
import zoneinfo
from dataclasses import dataclass

import boto3
import botocore.config
import botocore.exceptions

from analytics.config import (
    DEFAULT_ROLLUP_DELAY_MINUTES,
    AnalyticsConfig,
)
from analytics.history import (
    ClickHouseError,
    _clickhouse_command,
    _clickhouse_query,
    _clickhouse_request,
)

_logger = logging.getLogger(__name__)

# The daily availability rollup's constants (14.1 D-45..D-53, D-57).
AVAILABILITY_SCHEMA_VERSION = 1
ROLLUP_RETRY_SECONDS = 300
FOLDERLESS_GROUP_KEY = "(no folder)"
FLEET_GROUP_KEY = "all"

# `history.availability_daily` is not one of analytics' own tables, so the
# shared `history._clickhouse_insert` allowlist deliberately does not include
# it.  The table name is interpolated into the SQL text (no parameterized
# identifiers over HTTP), hence this separate one-name allowlist.
_ROLLUP_INSERT_TABLES = frozenset({"history.availability_daily"})


def _insert_availability_rows(
    base_url: str,
    user: str,
    password: str,
    table: str,
    rows: list[dict],
    timeout: float,
) -> None:
    """POST `rows` as one `INSERT INTO {table} FORMAT JSONEachRow` batch (D-44).

    `table` must be in `_ROLLUP_INSERT_TABLES` (T-14.1-08).  An empty `rows`
    list is a no-op.  `allow_nan=False` guards against sending a value
    ClickHouse would reject anyway.
    """
    if not rows:
        return
    if table not in _ROLLUP_INSERT_TABLES:
        raise ClickHouseError(f"Refusing to insert into unlisted table {table!r}")
    try:
        body = "\n".join(json.dumps(row, allow_nan=False) for row in rows).encode("utf-8")
    except ValueError as exc:
        raise ClickHouseError(f"Refusing to insert non-finite value into {table}: {exc}") from exc
    url = f"{base_url}/?query=" + urllib.parse.quote(f"INSERT INTO {table} FORMAT JSONEachRow")
    _clickhouse_request(url, user=user, password=password, timeout=timeout, data=body, method="POST")


def local_day_bounds(
    day: datetime.date, tz: zoneinfo.ZoneInfo
) -> tuple[datetime.datetime, datetime.datetime]:
    """Local midnight of `day` and of `day + 1`, both converted to UTC (D-49).

    This Python-computed boundary is the source of truth for the SQL
    window `fetch_host_day_counts()` below queries with -- never the
    container's own `TZ`, and never ClickHouse's own `toDate(ts, tz)`,
    which is only good for an independent server-side sanity check
    (research Anti-Patterns).
    """
    start_local = datetime.datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + datetime.timedelta(days=1)
    return start_local.astimezone(datetime.UTC), end_local.astimezone(datetime.UTC)


def rollup_days_to_check(
    today_local: datetime.date, first_data_day: datetime.date | None, backfill_days: int
) -> list[datetime.date]:
    """Ascending list of days eligible for a rollup: from the backfill floor up to yesterday (D-52).

    Never a day before `first_data_day` -- a pre-deployment day would
    otherwise be reported as 100% no-data -- and never `today_local`
    itself, which is still in progress. Returns `[]` when there is no
    recorded data yet (`first_data_day` is `None`) or when
    `first_data_day` is not strictly before `today_local`.
    """
    if first_data_day is None or first_data_day >= today_local:
        return []
    earliest = max(today_local - datetime.timedelta(days=backfill_days), first_data_day)
    latest = today_local - datetime.timedelta(days=1)
    if earliest > latest:
        return []
    days: list[datetime.date] = []
    current = earliest
    while current <= latest:
        days.append(current)
        current += datetime.timedelta(days=1)
    return days


def rollup_object_keys(day: datetime.date) -> tuple[str, str]:
    """Return `(json_key, parquet_key)` for `day` (D-53/D-57, Hive-style `date=` prefix)."""
    iso = day.isoformat()
    json_key = f"availability/{day:%Y}/{day:%m}/{iso}.json"
    parquet_key = f"availability_parquet/date={iso}/availability.parquet"
    return json_key, parquet_key


def _rollup_count(raw: object) -> int:
    """Coerce a sample count to a non-negative int; any unparsable value counts as 0.

    Matches this module's existing skip-not-fatal posture (`parse_perf_data`,
    `compute_incidents`): a ClickHouse row is trusted input in production,
    but a test or a schema drift should degrade, not crash the rollup.
    """
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


def compute_daily_availability(
    day: datetime.date,
    host_rows: list[dict],
    poll_interval_seconds: int,
    day_seconds: int = 86400,
) -> list[dict]:
    """Compute UP/DOWN/UNOBSERVED/downtime/no-data minutes and percentages for one day.

    Pure function, no I/O, never raises (matches `parse_perf_data()`'s
    posture): garbage/unparsable sample counts in `host_rows` degrade to 0
    via `_rollup_count()`.

    Each sample represents `poll_interval_seconds` of wall-clock time;
    `expected` minutes is always `day_seconds / 60`, regardless of how
    many samples were actually observed. `no_data = max(expected -
    observed, 0)` (D-47); the percentage base is `max(expected, observed)`
    so a day with MORE samples than expected (e.g. a brief double-poll)
    still sums to ~100% rather than exceeding it, and `no_data` never goes
    negative in that same case.

    `availability_pct = up / (up + down) * 100`, or `None` when
    `up + down == 0` -- UNREACHABLE is excluded from the denominator per
    D-45, scheduled downtime per D-46, no-data per D-47: none of the three
    ever counts as "up" or "down" for this figure.

    Known approximation: counting samples this way assumes the poll
    interval was constant for the whole day -- a mid-day
    `POLL_INTERVAL_SECONDS` change is not detectable from the stored
    samples alone.

    Rows are returned in this order: one per device (sorted by host), then
    one per folder (`group_type` "folder", `entity_key` = the folder path
    or `FOLDERLESS_GROUP_KEY` for an empty folder, figures summed across
    that folder's devices' minutes and bases, `device_count` the number of
    devices in it), then one fleet-wide row (`group_type` "fleet",
    `entity_key` `FLEET_GROUP_KEY`, always present even when `host_rows`
    is empty). The generic `group_type`/`entity_key` pair lets a future
    phase add a location group without a format change (D-48).
    """

    def _raw_figures(up_s: int, down_s: int, unreach_s: int, downtime_s: int) -> dict[str, float]:
        up = up_s * poll_interval_seconds / 60
        down = down_s * poll_interval_seconds / 60
        unobserved = unreach_s * poll_interval_seconds / 60
        downtime = downtime_s * poll_interval_seconds / 60
        observed = up + down + unobserved + downtime
        expected = day_seconds / 60
        no_data = max(expected - observed, 0.0)
        base = max(expected, observed)
        return {
            "up_minutes": up,
            "down_minutes": down,
            "unobserved_minutes": unobserved,
            "downtime_minutes": downtime,
            "no_data_minutes": no_data,
            "base": base,
        }

    def _sum_raw(raws: list[dict[str, float]]) -> dict[str, float]:
        return {
            key: sum(raw[key] for raw in raws)
            for key in (
                "up_minutes",
                "down_minutes",
                "unobserved_minutes",
                "downtime_minutes",
                "no_data_minutes",
                "base",
            )
        }

    def _round_figures(raw: dict[str, float]) -> dict[str, float | None]:
        base = raw["base"]

        def _pct(minutes: float) -> float:
            return round(minutes / base * 100, 3) if base else 0.0

        denom = raw["up_minutes"] + raw["down_minutes"]
        availability = round(raw["up_minutes"] / denom * 100, 3) if denom else None
        return {
            "up_minutes": round(raw["up_minutes"], 2),
            "down_minutes": round(raw["down_minutes"], 2),
            "unobserved_minutes": round(raw["unobserved_minutes"], 2),
            "downtime_minutes": round(raw["downtime_minutes"], 2),
            "no_data_minutes": round(raw["no_data_minutes"], 2),
            "up_pct": _pct(raw["up_minutes"]),
            "down_pct": _pct(raw["down_minutes"]),
            "unobserved_pct": _pct(raw["unobserved_minutes"]),
            "downtime_pct": _pct(raw["downtime_minutes"]),
            "no_data_pct": _pct(raw["no_data_minutes"]),
            "availability_pct": availability,
        }

    day_iso = day.isoformat()
    device_entries: list[tuple[str, str, dict[str, float]]] = []
    rows: list[dict] = []

    for host_row in sorted(host_rows, key=lambda row: str(row.get("host", ""))):
        host = str(host_row.get("host", ""))
        folder = str(host_row.get("folder") or "")
        raw = _raw_figures(
            _rollup_count(host_row.get("up_samples")),
            _rollup_count(host_row.get("down_samples")),
            _rollup_count(host_row.get("unreach_samples")),
            _rollup_count(host_row.get("downtime_samples")),
        )
        device_entries.append((host, folder, raw))
        rows.append(
            {
                "day": day_iso,
                "entity_type": "device",
                "group_type": "",
                "entity_key": host,
                "folder": folder,
                "device_count": 1,
                "schema_version": AVAILABILITY_SCHEMA_VERSION,
                **_round_figures(raw),
            }
        )

    folder_groups: dict[str, list[dict[str, float]]] = {}
    for _host, folder, raw in device_entries:
        key = folder or FOLDERLESS_GROUP_KEY
        folder_groups.setdefault(key, []).append(raw)

    for key in sorted(folder_groups):
        raws = folder_groups[key]
        rows.append(
            {
                "day": day_iso,
                "entity_type": "group",
                "group_type": "folder",
                "entity_key": key,
                "folder": key,
                "device_count": len(raws),
                "schema_version": AVAILABILITY_SCHEMA_VERSION,
                **_round_figures(_sum_raw(raws)),
            }
        )

    if device_entries:
        fleet_raws = [raw for _host, _folder, raw in device_entries]
        fleet_figures = _round_figures(_sum_raw(fleet_raws))
        fleet_device_count = len(fleet_raws)
    else:
        expected_minutes = round(day_seconds / 60, 2)
        fleet_figures = {
            "up_minutes": 0.0,
            "down_minutes": 0.0,
            "unobserved_minutes": 0.0,
            "downtime_minutes": 0.0,
            "no_data_minutes": expected_minutes,
            "up_pct": 0.0,
            "down_pct": 0.0,
            "unobserved_pct": 0.0,
            "downtime_pct": 0.0,
            "no_data_pct": 100.0,
            "availability_pct": None,
        }
        fleet_device_count = 0

    rows.append(
        {
            "day": day_iso,
            "entity_type": "group",
            "group_type": "fleet",
            "entity_key": FLEET_GROUP_KEY,
            "folder": "",
            "device_count": fleet_device_count,
            "schema_version": AVAILABILITY_SCHEMA_VERSION,
            **fleet_figures,
        }
    )

    return rows


_AVAILABILITY_FIGURE_KEYS = (
    "up_minutes",
    "down_minutes",
    "unobserved_minutes",
    "downtime_minutes",
    "no_data_minutes",
    "up_pct",
    "down_pct",
    "unobserved_pct",
    "downtime_pct",
    "no_data_pct",
    "availability_pct",
)


def availability_document(
    day: datetime.date,
    rows: list[dict],
    *,
    timezone_name: str,
    poll_interval_seconds: int,
    generated_at_iso: str,
) -> dict:
    """Build the day's JSON rollup document directly from `rows` -- never recomputed (D-53/D-57).

    A pure reshape of `compute_daily_availability()`'s own output into the
    devices/groups document shape: the JSON and the Parquet export (which
    reads these same rows back out of ClickHouse) can never drift from
    each other by construction, since neither recomputes any figure.
    """
    devices = [
        {
            "host": row.get("entity_key"),
            "folder": row.get("folder"),
            **{key: row.get(key) for key in _AVAILABILITY_FIGURE_KEYS},
        }
        for row in rows
        if row.get("entity_type") == "device"
    ]
    groups = [
        {
            "group_type": row.get("group_type"),
            "group_key": row.get("entity_key"),
            "device_count": row.get("device_count"),
            **{key: row.get(key) for key in _AVAILABILITY_FIGURE_KEYS},
        }
        for row in rows
        if row.get("entity_type") == "group"
    ]
    return {
        "schema_version": AVAILABILITY_SCHEMA_VERSION,
        "date": day.isoformat(),
        "timezone": timezone_name,
        "poll_interval_seconds": poll_interval_seconds,
        "generated_at": generated_at_iso,
        "definitions": {
            "up_pct": "Percentage of the day this entity was reachable and OK (D-45).",
            "down_pct": "Percentage of the day this entity was confirmed DOWN (D-45).",
            "unobserved_pct": (
                "Percentage of the day this entity was UNREACHABLE; excluded from "
                "availability as not observable (D-45)."
            ),
            "downtime_pct": (
                "Percentage of the day this entity was in scheduled downtime; "
                "excluded from availability (D-46)."
            ),
            "no_data_pct": (
                "Percentage of the day with no poller data; excluded from "
                "availability (D-47)."
            ),
            "availability_pct": (
                "up / (up + down) * 100; null when neither was observed this day (D-45)."
            ),
        },
        "devices": devices,
        "groups": groups,
    }


def availability_document_problems(doc: dict) -> list[str]:
    """Human-readable problems with `doc`, project convention (like `_password_problems`).

    Returns `[]` when `doc` is well-formed. Never raises: a malformed
    `doc` (wrong types, missing keys) degrades to a problem message
    naming the issue rather than a traceback, since this gate runs
    immediately before a JSON PUT (`rollup_one_day()` below) and must
    always be able to explain a refusal.
    """
    problems: list[str] = []
    if doc.get("schema_version") != AVAILABILITY_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {AVAILABILITY_SCHEMA_VERSION}, got {doc.get('schema_version')!r}"
        )
    try:
        datetime.date.fromisoformat(str(doc.get("date")))
    except (TypeError, ValueError):
        problems.append(f"date {doc.get('date')!r} is not a valid ISO date")

    devices = doc.get("devices")
    if not isinstance(devices, list):
        problems.append("devices must be a list")
        devices = []
    groups = doc.get("groups")
    if not isinstance(groups, list):
        problems.append("groups must be a list")
        groups = []

    def _check_numeric(entry: dict, label: str, key: str, *, allow_none: bool) -> None:
        value = entry.get(key)
        if value is None and allow_none:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{label} {key} is not numeric: {value!r}")
        elif not (0 <= value <= 100.001):
            problems.append(f"{label} {key} is out of range 0..100: {value!r}")

    def _check_entry(entry: object, label: str) -> None:
        if not isinstance(entry, dict):
            problems.append(f"{label} entry is not an object: {entry!r}")
            return
        for key in (
            "up_pct",
            "down_pct",
            "unobserved_pct",
            "downtime_pct",
            "no_data_pct",
        ):
            _check_numeric(entry, label, key, allow_none=False)
        _check_numeric(entry, label, "availability_pct", allow_none=True)

    for entry in devices:
        _check_entry(entry, "device")
    for entry in groups:
        _check_entry(entry, "group")

    return problems


class RollupError(RuntimeError):
    """Raised when the availability rollup for a day cannot be safely written.

    Caught at `run_rollups()`'s per-day call site and logged -- never
    allowed to abort the rest of the backfill window or the poll loop
    (D-44).
    """


def build_s3_client(config: AnalyticsConfig):
    """Build a `boto3` S3 client from `config`'s `S3_*` settings (D-41).

    Plain S3 API only -- no MinIO-specific calls anywhere in this module.
    Portable to AWS S3 by configuration alone: point `S3_ENDPOINT` at the
    regional AWS endpoint (or leave it unset and let boto3 resolve AWS's
    own default), set `S3_REGION`, and switch `S3_ADDRESSING_STYLE` to
    "virtual" -- no code change is needed (D-41).
    """
    return boto3.client(
        "s3",
        endpoint_url=config.s3_endpoint,
        aws_access_key_id=config.s3_access_key,
        aws_secret_access_key=config.s3_secret_key,
        region_name=config.s3_region,
        config=botocore.config.Config(
            signature_version="s3v4",
            s3={"addressing_style": config.s3_addressing_style},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def object_exists(s3, bucket: str, key: str) -> bool:
    """True if `key` exists in `bucket`, checked via HEAD (never a GET, no body transfer)."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def write_if_absent(s3, bucket: str, key: str, payload: bytes, content_type: str) -> bool:
    """HEAD-before-PUT: write `payload` to `key` only if it does not already exist (D-52/D-57).

    HEAD-before-PUT, not a conditional PUT (`If-None-Match`): MinIO's
    support for the wildcard conditional-write semantic is
    version-dependent (research Pitfall 2), while HEAD-before-PUT works
    identically on every S3-compatible backend. The narrow TOCTOU window
    this leaves is accepted -- the rollup job is a single writer, running
    at most once per day per object.
    """
    if object_exists(s3, bucket, key):
        return False
    s3.put_object(Bucket=bucket, Key=key, Body=payload, ContentType=content_type)
    return True


# Phase 14.1: the rollup timezone name is interpolated directly into SQL
# (`fetch_first_data_day()` below has no parameterized-identifier syntax to
# fall back on, the same constraint `_clickhouse_insert`'s table allowlist
# works around for table names) -- reject anything that is not
# letters/underscores/hyphens/pluses separated by slashes before it ever
# reaches a query.
_TZ_NAME_RE = re.compile(r"^[A-Za-z_]+(/[A-Za-z_+-]+)*$")


def _validate_tz_name(name: str) -> str:
    """Return `name` unchanged if it looks like a safe IANA zone name, else raise `RollupError`."""
    if not _TZ_NAME_RE.match(name or ""):
        raise RollupError(f"Refusing to use unsafe timezone name in SQL: {name!r}")
    return name


def fetch_first_data_day(config: AnalyticsConfig, tz_name: str) -> datetime.date | None:
    """Return the earliest local calendar day with any `history.host_state` row, or `None` if empty.

    Bounds D-52's backfill window from below: never roll up a day before
    the fleet actually had data, which would otherwise report a
    pre-deployment day as 100% no-data. `tz_name` must already be
    validated by the caller (`run_rollups()`) since it is interpolated
    into this query's SQL text.
    """
    rows = _clickhouse_query(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        f"SELECT toString(toDate(min(ts), '{tz_name}')) AS d, count() AS n FROM history.host_state",
        config.clickhouse_timeout_seconds,
    )
    if not rows or int(rows[0].get("n", 0)) == 0:
        return None
    return datetime.date.fromisoformat(rows[0]["d"])


def fetch_host_day_counts(
    config: AnalyticsConfig, start_utc: datetime.datetime, end_utc: datetime.datetime
) -> list[dict]:
    """Per-host up/down/unreach/downtime sample counts for `[start_utc, end_utc)` (D-51).

    Computed fresh from ClickHouse's durable `history.host_state` table on
    every call -- never from in-memory poller counters -- so a poller
    restart mid-day cannot lose or corrupt that day's figures.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "SELECT host, argMax(folder, ts) AS folder, "
        "sumIf(samples, state = 0 AND in_downtime = 0) AS up_samples, "
        "sumIf(samples, state = 1 AND in_downtime = 0) AS down_samples, "
        "sumIf(samples, state = 2 AND in_downtime = 0) AS unreach_samples, "
        "sumIf(samples, in_downtime = 1) AS downtime_samples "
        "FROM history.host_state "
        f"WHERE ts >= toDateTime('{start_str}', 'UTC') AND ts < toDateTime('{end_str}', 'UTC') "
        "GROUP BY host ORDER BY host"
    )
    return _clickhouse_query(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        sql,
        config.clickhouse_timeout_seconds,
    )


# Phase 14.1 (D-57): a single quote or backslash in an S3 credential would
# break out of the SQL string literal `export_parquet()` builds below --
# ClickHouse's `s3()` table function has no parameterized-credential form,
# so this is the same defense-before-interpolation posture as
# `_TZ_NAME_RE` above.
_SQL_UNSAFE_CREDENTIAL_RE = re.compile(r"['\\]")


def export_parquet(config: AnalyticsConfig, day: datetime.date, parquet_key: str) -> None:
    """Export `day`'s already-inserted `history.availability_daily` rows to Parquet (D-57).

    ClickHouse writes the Parquet directly from the rows the poller just
    inserted into `history.availability_daily`, so the JSON (written from
    that same in-memory row list by `rollup_one_day()`) and this Parquet
    twin carry identical figures by construction -- never a second,
    independently-computed pass that could drift (research Anti-Patterns).

    Refuses (`ClickHouseError`, no request sent) if the S3 access key or
    secret contains a single quote or backslash, since both are
    interpolated directly into the SQL statement's string literals. By
    default ClickHouse refuses to overwrite an existing `s3()` object
    (`s3_truncate_on_insert` is never set here) -- a second never-overwrite
    layer behind `write_if_absent()`'s own `object_exists()` check.
    Verified via context7 (clickhouse/clickhouse-docs,
    docs/sql-reference/table-functions/s3.md: `INSERT INTO FUNCTION
    s3(...)` fails on an existing key unless `s3_truncate_on_insert=1` is
    set) and that `s3()` credentials are masked in ClickHouse's own query
    logs (clickhouse/clickhouse-docs, docs/operations/server-configuration-
    parameters/settings.md `query_masking_rules`: the server's built-in
    default masking rules redact S3 URL credentials before they reach any
    log). This poller never logs the credentials either.
    """
    if _SQL_UNSAFE_CREDENTIAL_RE.search(config.s3_access_key) or _SQL_UNSAFE_CREDENTIAL_RE.search(
        config.s3_secret_key
    ):
        raise ClickHouseError("Refusing Parquet export: S3 credential contains an unsafe character")
    s3_url = f"{config.s3_endpoint}/{config.availability_bucket}/{parquet_key}"
    sql = (
        f"INSERT INTO FUNCTION s3('{s3_url}', '{config.s3_access_key}', '{config.s3_secret_key}', "
        "'Parquet') "
        "SELECT day, entity_type, group_type, entity_key, folder, device_count, "
        "up_minutes, down_minutes, unobserved_minutes, downtime_minutes, no_data_minutes, "
        "up_pct, down_pct, unobserved_pct, downtime_pct, no_data_pct, availability_pct, "
        "schema_version, generated_at "
        "FROM history.availability_daily FINAL "
        f"WHERE day = toDate('{day.isoformat()}') "
        "ORDER BY entity_type, group_type, entity_key"
    )
    _clickhouse_command(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        sql,
        config.clickhouse_timeout_seconds,
    )


def rollup_one_day(config: AnalyticsConfig, s3, tz: zoneinfo.ZoneInfo, day: datetime.date) -> str:
    """Compute and write one day's availability rollup if either object is missing (D-52/D-57).

    Returns "skipped" when both the JSON and Parquet objects already
    exist (never overwrite). Otherwise fetches this day's counts from
    ClickHouse, computes the figures, inserts them into
    `history.availability_daily`, exports the Parquet twin if missing,
    then writes the JSON if missing, and returns "written". A day left
    half-written by a prior run (only one of the two objects exists) is
    completed here -- the existing object is never touched again.
    """
    json_key, parquet_key = rollup_object_keys(day)
    json_exists = object_exists(s3, config.availability_bucket, json_key)
    parquet_exists = object_exists(s3, config.availability_bucket, parquet_key)
    if json_exists and parquet_exists:
        return "skipped"

    start_utc, end_utc = local_day_bounds(day, tz)
    host_rows = fetch_host_day_counts(config, start_utc, end_utc)
    rows = compute_daily_availability(
        day, host_rows, config.poll_interval_seconds, int((end_utc - start_utc).total_seconds())
    )

    generated_at = datetime.datetime.now(datetime.UTC)
    generated_at_str = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    _insert_availability_rows(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        "history.availability_daily",
        [{**row, "generated_at": generated_at_str} for row in rows],
        config.clickhouse_timeout_seconds,
    )

    if not parquet_exists:
        export_parquet(config, day, parquet_key)

    if not json_exists:
        doc = availability_document(
            day,
            rows,
            timezone_name=str(tz),
            poll_interval_seconds=config.poll_interval_seconds,
            generated_at_iso=generated_at.isoformat(),
        )
        problems = availability_document_problems(doc)
        if problems:
            raise RollupError(
                f"Refusing to write availability document for {day}: {'; '.join(problems)}"
            )
        write_if_absent(
            s3,
            config.availability_bucket,
            json_key,
            json.dumps(doc).encode("utf-8"),
            "application/json",
        )

    return "written"


def run_rollups(
    config: AnalyticsConfig, s3, today_local: datetime.date
) -> tuple[list[datetime.date], int]:
    """Roll up every missing day back to the backfill floor, oldest first (D-52).

    A day whose rollup raises is logged and skipped -- one bad day never
    blocks the rest of the backfill window. A failure resolving the
    fleet's first recorded day propagates to the caller
    (`maybe_run_rollups()` below): without it there is no way to know
    which days are even eligible.
    """
    tz_name = _validate_tz_name(config.rollup_tz)
    tz = zoneinfo.ZoneInfo(tz_name)
    first_data_day = fetch_first_data_day(config, tz_name)
    written: list[datetime.date] = []
    failures = 0
    for day in rollup_days_to_check(today_local, first_data_day, config.rollup_backfill_days):
        try:
            result = rollup_one_day(config, s3, tz, day)
        except (
            ClickHouseError,
            RollupError,
            botocore.exceptions.BotoCoreError,
            botocore.exceptions.ClientError,
        ) as exc:
            _logger.warning("Availability rollup for %s failed; will retry later: %s", day, exc)
            failures += 1
            continue
        if result == "written":
            written.append(day)
            _logger.info("Availability rollup written for %s (JSON + Parquet)", day)
    return written, failures


@dataclass
class RollupScheduler:
    """Tracks when the next availability-rollup attempt is due (D-49/D-51/D-52).

    In-memory only -- a poller restart simply re-evaluates `due()` as
    freshly due again, which is safe because every object write below it
    is never-overwrite (D-44/D-52): a restart mid-backfill just repeats
    the days that already succeeded as no-ops.
    """

    last_completed_local_date: datetime.date | None = None
    next_attempt_monotonic: float = 0.0
    delay_minutes: int = DEFAULT_ROLLUP_DELAY_MINUTES

    def due(self, now_local: datetime.datetime, now_monotonic: float) -> bool:
        if now_monotonic < self.next_attempt_monotonic:
            return False
        if self.last_completed_local_date is None:
            return True
        if now_local.date() == self.last_completed_local_date:
            return False
        return now_local.time() >= datetime.time(0, self.delay_minutes)

    def mark_success(self, local_date: datetime.date) -> None:
        self.last_completed_local_date = local_date
        self.next_attempt_monotonic = 0.0

    def mark_failure(self, now_monotonic: float) -> None:
        self.next_attempt_monotonic = now_monotonic + ROLLUP_RETRY_SECONDS


def maybe_run_rollups(
    config: AnalyticsConfig,
    scheduler: RollupScheduler,
    s3_holder: dict,
    tz: zoneinfo.ZoneInfo,
    now_local: datetime.datetime,
    now_monotonic: float,
) -> None:
    """Run the availability-rollup backfill once it is due, never letting a failure reach the poll loop.

    A no-op (no S3 client built, no ClickHouse query) until both
    `clickhouse_url` and `s3_endpoint` are configured -- mirrors
    `write_history()`'s "unset means disabled" posture. The one
    deliberate broad `except Exception` here matches the REST
    folder-lookup's never-fatal posture (D-44): the rollup job is
    enrichment, and no failure in it -- expected
    (`ClickHouseError`/`RollupError`/`botocore`) or not -- may ever crash
    the poller.
    """
    if not config.clickhouse_url or not config.s3_endpoint:
        return
    if not scheduler.due(now_local, now_monotonic):
        return
    try:
        if "client" not in s3_holder:
            s3_holder["client"] = build_s3_client(config)
        _written, failures = run_rollups(config, s3_holder["client"], now_local.date())
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring above
        _logger.warning(
            "Availability rollup run failed; retrying in %ss: %s", ROLLUP_RETRY_SECONDS, exc
        )
        scheduler.mark_failure(now_monotonic)
        return
    if failures == 0:
        scheduler.mark_success(now_local.date())
    else:
        scheduler.mark_failure(now_monotonic)
