-- 14.2 analytics migration for an EXISTING ClickHouse volume.
--
-- initdb (01-schema.sql / 02-users.sh) never re-runs on a non-empty data
-- volume ("Init scripts never re-run on a non-empty ClickHouse data volume",
-- 02-users.sh), so hosts that already have a volume apply this file once. Run it
-- from deploy/ on the deploy host:
--
--   set -a; . ./.env; set +a
--   sed "s/@CH_ANALYTICS_PASSWORD@/$CH_ANALYTICS_PASSWORD/" clickhouse-config/migrations/14.2-analytics.sql | podman exec -i clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" --multiquery
--
-- Safe to re-run: every CREATE is IF NOT EXISTS and GRANT is idempotent.
-- `podman exec` is not a container restart. The secret must stay [A-Za-z0-9_-]
-- (init-env.sh guarantees it) because it is spliced into the SQL string literal.
-- The tracked file holds only the placeholder; the real value exists only in
-- the operator's shell pipe.

-- history.events (14.2 D-02, D-03): durable copy of the published state-change /
-- added / removed events. from_state / to_state are not named from / to because
-- those are SQL keywords; '' stands for JSON null.
-- The ORDER BY is the dedup key (ReplacingMergeTree), belt and braces for the
-- in-memory dedup in the analytics container.
CREATE TABLE IF NOT EXISTS history.events
(
    ts          DateTime('UTC'),
    device_id   LowCardinality(String),
    event       LowCardinality(String), -- state_change / added / removed as published
    from_state  LowCardinality(String) DEFAULT '',
    to_state    LowCardinality(String) DEFAULT '',
    recorded_at DateTime('UTC') DEFAULT now()
)
ENGINE = ReplacingMergeTree(recorded_at)
PARTITION BY toYYYYMM(ts)
ORDER BY (device_id, ts, event, from_state, to_state)
TTL ts + INTERVAL 1095 DAY DELETE;

-- history.incidents (14.2 D-02, D-03, D-30): one row per incident, rewritten as
-- it changes. ReplacingMergeTree(updated_at) keeps the latest version; readers
-- must use FINAL.
CREATE TABLE IF NOT EXISTS history.incidents
(
    incident_id       LowCardinality(String),
    opened_at         DateTime('UTC'),
    closed_at         Nullable(DateTime('UTC')),
    duration_s        Nullable(UInt32),
    status            LowCardinality(String), -- open / closed
    close_source      LowCardinality(String) DEFAULT '', -- tombstone / reconcile
    root              LowCardinality(String),
    root_state        LowCardinality(String),
    inferred          UInt8,
    confirmed_down    Array(String),
    not_observable    Array(String),
    dependents        Array(String),
    worst_criticality LowCardinality(String),
    summary           String, -- D-30: closed summary, or the latest open narration headline
    updated_at        DateTime('UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (incident_id, opened_at)
TTL toDate(opened_at) + INTERVAL 1095 DAY DELETE;

-- history.need_triage (14.2 D-21, D-23): append-only audit log of operator
-- triage actions on the "needs attention" list.
CREATE TABLE IF NOT EXISTS history.need_triage
(
    ts            DateTime('UTC'),
    need_id       String,
    source        LowCardinality(String),
    host          LowCardinality(String),
    service       String DEFAULT '',
    metric        String DEFAULT '',
    action        LowCardinality(String), -- downgrade / upgrade / cancel / auto_reset
    computed_tier LowCardinality(String),
    tier_before   LowCardinality(String),
    tier_after    LowCardinality(String),
    note          String DEFAULT '',
    actor         String DEFAULT '',
    command_id    String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (ts, need_id)
TTL ts + INTERVAL 1095 DAY DELETE;

-- analytics_writer: same grants as initdb/02-users.sh.
CREATE USER IF NOT EXISTS analytics_writer IDENTIFIED WITH sha256_password BY '@CH_ANALYTICS_PASSWORD@';
GRANT SELECT, INSERT ON history.* TO analytics_writer;
GRANT S3 ON *.* TO analytics_writer;
GRANT CREATE TEMPORARY TABLE ON *.* TO analytics_writer;
