-- History schema: metric/state series and the availability-rollup staging
-- table (D-21, D-40b, D-42, D-43, D-48). Runs once, before 02-users.sh, on
-- the first start of an empty ClickHouse data volume (docker-entrypoint-initdb.d,
-- verified via ctx7, clickhouse/clickhouse-docs: scripts in this directory run
-- in alphabetical order before the server accepts connections).
--
-- TTL `GROUP BY` columns must be a left-prefix of each table's ORDER BY /
-- PRIMARY KEY (verified via ctx7, clickhouse/clickhouse-docs,
-- docs/guides/developer/ttl.md: "The GROUP BY columns in the TTL clause must
-- be a prefix of the PRIMARY KEY") -- this is why toStartOfHour(ts) precedes
-- toStartOfFiveMinutes(ts) in every ORDER BY below: the coarser 1-hour rollup
-- (365-day rule) must itself be a prefix of the finer 5-minute rollup
-- (30-day rule)'s key.
--
-- Columns that are not named in a TTL rule's SET clause (warn, crit, folder)
-- keep an arbitrary ("any one row from the bucket") value after that rule
-- fires, per the same ttl.md rollup mechanics -- they are not aggregated, only
-- carried along. Long-range Grafana queries should bucket by
-- toStartOfFiveMinutes(ts)/toStartOfHour(ts) rather than trust a single
-- warn/crit reading beyond the 30-day raw window.
--
-- Unverified at plan time: whether this ClickHouse server accepts two
-- GROUP BY TTL rules on one table (the 30-day 5-minute rule and the 365-day
-- 1-hour rule together) is proven only by live verification (plan 14.1-08).
-- If it is rejected, the documented fallback is to delete the 365-day rule
-- from metrics/host_state/service_state below, keeping 5-minute resolution
-- for the full 3 years -- still inside D-40b's "e.g." shape.

CREATE DATABASE IF NOT EXISTS history;

-- history.metrics: every parsed perf_data metric from every service (D-42).
-- value becomes the bucket mean once a rollup rule has fired; value_min/max/
-- sum/count stay trustworthy aggregates at every resolution. Keys are only
-- host/service/metric (LowCardinality) -- never a free-text or high-
-- cardinality field (Pitfall 5).
CREATE TABLE IF NOT EXISTS history.metrics
(
    ts          DateTime('UTC'),
    host        LowCardinality(String),
    service     LowCardinality(String),
    metric      LowCardinality(String),
    value       Float64,
    warn        Nullable(Float64),
    crit        Nullable(Float64),
    value_min   Float64 DEFAULT value,
    value_max   Float64 DEFAULT value,
    value_sum   Float64 DEFAULT value,
    value_count UInt32 DEFAULT 1
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (host, service, metric, toStartOfHour(ts), toStartOfFiveMinutes(ts), ts)
TTL
    ts + INTERVAL 30 DAY
        GROUP BY host, service, metric, toStartOfHour(ts), toStartOfFiveMinutes(ts)
        SET value = sum(value_sum) / sum(value_count),
            value_min = min(value_min),
            value_max = max(value_max),
            value_sum = sum(value_sum),
            value_count = sum(value_count),
    ts + INTERVAL 365 DAY
        GROUP BY host, service, metric, toStartOfHour(ts)
        SET value = sum(value_sum) / sum(value_count),
            value_min = min(value_min),
            value_max = max(value_max),
            value_sum = sum(value_sum),
            value_count = sum(value_count),
    ts + INTERVAL 31 DAY TO VOLUME 's3',
    ts + INTERVAL 1095 DAY DELETE
SETTINGS storage_policy = 's3_tiered';

-- history.host_state: per-host UP/DOWN/UNREACHABLE series with a downtime
-- flag and folder (D-43). Downsampled buckets keep the WORST state (max of
-- the UInt8 code, so DOWN/UNREACHABLE outrank UP) -- folder keeps an
-- arbitrary value, since it does not change within a host's rollup bucket.
-- Availability rollups (D-51) only ever read rows younger than 28 days,
-- which are still raw (well inside the 30-day TTL boundary).
CREATE TABLE IF NOT EXISTS history.host_state
(
    ts          DateTime('UTC'),
    host        LowCardinality(String),
    folder      LowCardinality(String),
    state       UInt8, -- 0 UP, 1 DOWN, 2 UNREACHABLE
    in_downtime UInt8, -- 0 or 1
    samples     UInt32 DEFAULT 1
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (host, toStartOfHour(ts), toStartOfFiveMinutes(ts), ts)
TTL
    ts + INTERVAL 30 DAY
        GROUP BY host, toStartOfHour(ts), toStartOfFiveMinutes(ts)
        SET state = max(state), in_downtime = max(in_downtime), samples = sum(samples),
    ts + INTERVAL 365 DAY
        GROUP BY host, toStartOfHour(ts)
        SET state = max(state), in_downtime = max(in_downtime), samples = sum(samples),
    ts + INTERVAL 31 DAY TO VOLUME 's3',
    ts + INTERVAL 1095 DAY DELETE
SETTINGS storage_policy = 's3_tiered';

-- history.service_state: per-service OK/WARN/CRIT/UNKNOWN series (D-43).
-- max(state) ranks UNKNOWN (3) above CRIT (2) in downsampled buckets, unlike
-- Checkmk's own worst-state ordering (CRIT worse than UNKNOWN) -- accepted
-- here because this table only serves long-range Grafana timelines, never
-- the live dashboard, which reads Checkmk's current state directly.
CREATE TABLE IF NOT EXISTS history.service_state
(
    ts      DateTime('UTC'),
    host    LowCardinality(String),
    service LowCardinality(String),
    state   UInt8, -- 0 OK, 1 WARN, 2 CRIT, 3 UNKNOWN
    samples UInt32 DEFAULT 1
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (host, service, toStartOfHour(ts), toStartOfFiveMinutes(ts), ts)
TTL
    ts + INTERVAL 30 DAY
        GROUP BY host, service, toStartOfHour(ts), toStartOfFiveMinutes(ts)
        SET state = max(state), samples = sum(samples),
    ts + INTERVAL 365 DAY
        GROUP BY host, service, toStartOfHour(ts)
        SET state = max(state), samples = sum(samples),
    ts + INTERVAL 31 DAY TO VOLUME 's3',
    ts + INTERVAL 1095 DAY DELETE
SETTINGS storage_policy = 's3_tiered';

-- history.availability_daily: staging table for the daily rollup job's
-- Parquet export (D-57) and (later) Grafana's availability dashboard. A tiny
-- table (one row per device/folder/fleet per day) -- default storage, no S3
-- tiering needed. group_type is '' for a device row, 'folder' for a
-- per-folder (VLAN) group, or 'fleet' for the single fleet-wide row, leaving
-- room for later location types (D-48) without a schema change.
-- ReplacingMergeTree(generated_at) so a recomputed day (a backfill re-run)
-- replaces rather than duplicates rows -- readers must query with FINAL.
CREATE TABLE IF NOT EXISTS history.availability_daily
(
    day                 Date,
    entity_type         LowCardinality(String), -- 'device' or 'group'
    group_type          LowCardinality(String), -- '' / 'folder' / 'fleet'
    entity_key          String, -- host name, folder path, or 'all' for the fleet row
    folder              String,
    device_count        UInt32,
    up_minutes          Float64,
    down_minutes        Float64,
    unobserved_minutes  Float64,
    downtime_minutes    Float64,
    no_data_minutes     Float64,
    up_pct              Float64,
    down_pct            Float64,
    unobserved_pct      Float64,
    downtime_pct        Float64,
    no_data_pct         Float64,
    availability_pct    Nullable(Float64),
    schema_version      UInt16,
    generated_at        DateTime('UTC')
)
ENGINE = ReplacingMergeTree(generated_at)
ORDER BY (day, entity_type, group_type, entity_key)
TTL day + INTERVAL 1095 DAY DELETE;
