#!/usr/bin/env bash
# User and grant bootstrap for the history database (D-54, D-55, D-56).
#
# Runs from /docker-entrypoint-initdb.d after 01-schema.sql, only on the
# first start of an empty ClickHouse data volume (verified via ctx7,
# clickhouse/clickhouse-docs, docker-entrypoint-initdb.d bootstrap scripts run
# once, in alphabetical order, before the server accepts connections). This
# is why it is a .sh script, not a plain .sql file: passwords arrive via
# container env from deploy/.env (empty-default compose pattern, 10-REVIEW
# CR-01), never from a tracked file, and plain .sql init files get no env
# substitution.
#
# Because init scripts never re-run on a non-empty data volume, a
# misconfigured first start (an empty or unsafe password) must fail loudly
# here rather than silently create a weak user that a later `deploy/.env` fix
# would not retroactively correct.
set -euo pipefail

# Exits 1, naming the offending variable, if it is empty/unset or contains a
# character that would break the SQL string literal it is interpolated into
# below. Uses ${!name:-} (indirect expansion with a default) so `set -u`
# never aborts on a genuinely-unset variable before this check can report it.
# Never echoes the password value itself.
check_password() {
    local name="$1"
    local value="${!name:-}"
    if [ -z "$value" ]; then
        echo "ERROR: $name is empty or unset." >&2
        echo "Set it in deploy/.env, then run:" >&2
        echo "  podman compose down" >&2
        echo "  (remove the clickhouse_data volume)" >&2
        echo "  podman compose up -d" >&2
        echo "Init scripts never re-run on a non-empty ClickHouse data volume." >&2
        exit 1
    fi
    case "$value" in
        *\'* | *\"* | *\\* | *[[:space:]]*)
            echo "ERROR: $name contains a single quote, double quote, backslash or whitespace character, which would break the SQL literal it is used in." >&2
            echo "Set a safe value in deploy/.env, then run:" >&2
            echo "  podman compose down" >&2
            echo "  (remove the clickhouse_data volume)" >&2
            echo "  podman compose up -d" >&2
            echo "Init scripts never re-run on a non-empty ClickHouse data volume." >&2
            exit 1
            ;;
    esac
}

for password_var in CLICKHOUSE_PASSWORD CH_WRITER_PASSWORD CH_READER_PASSWORD CH_GRAFANA_PASSWORD CH_ANALYTICS_PASSWORD; do
    check_password "$password_var"
done

# history_reader_profile: readonly = 1 forbids writes/DDL and client SETTINGS
# overrides such as `readonly = 0` even over HTTP (ContextAccess.cpp's
# not_readonly_flags check applies regardless of client-supplied settings,
# verified via ctx7). max_execution_time is made CHANGEABLE_IN_READONLY
# because Grafana's clickhouse-go client sets it on every query, and
# ClickHouse's own Grafana integration guide recommends exactly this
# constraint kind (rather than readonly = 2) so a public/read-only user keeps
# readonly = 1 (verified via ctx7, clickhouse/clickhouse-docs,
# docs/integrations/data-visualization/grafana/index.md "Making a read-only
# user").
#
# Quick 261002-nm2: the cap was MAX 60, and every Grafana panel failed with code 452
# SETTING_CONSTRAINT_VIOLATION "setting max_execution_time shouldn't be greater than 60" (live,
# 2026-10-02): the Grafana plugin's client sends its own max_execution_time on every query, above
# 60 with the default query timeout. MAX 120 leaves room for it; the default for a plain query is
# still 30 s. This script only runs when the clickhouse_data volume is first created, so an
# existing host needs the one-off ALTER SETTINGS PROFILE in docs/DEPLOY-NEW-MACHINE.md.
#
# poller_writer's S3 table-function privilege (needed for the Parquet export,
# D-57) uses the legacy `GRANT S3 ON *.* TO user` form rather than the newer
# `GRANT READ, WRITE ON S3 TO user` form: verified via ctx7 (clickhouse-docs
# 2025 changelog) that the READ/WRITE source-privilege split is gated behind
# `access_control_improvements.enable_read_write_grants`, which is *disabled
# by default* and not turned on anywhere in this stack's config -- so the
# legacy form is the one that actually grants the privilege on this server.
clickhouse client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery <<SQL
CREATE SETTINGS PROFILE IF NOT EXISTS history_reader_profile
    SETTINGS readonly = 1, max_execution_time = 30 MAX 120 CHANGEABLE_IN_READONLY;

CREATE USER IF NOT EXISTS dashboard_reader IDENTIFIED WITH sha256_password BY '$CH_READER_PASSWORD'
    SETTINGS PROFILE 'history_reader_profile';
GRANT SELECT ON history.* TO dashboard_reader;

CREATE USER IF NOT EXISTS grafana_reader IDENTIFIED WITH sha256_password BY '$CH_GRAFANA_PASSWORD'
    SETTINGS PROFILE 'history_reader_profile';
GRANT SELECT ON history.* TO grafana_reader;

CREATE USER IF NOT EXISTS poller_writer IDENTIFIED WITH sha256_password BY '$CH_WRITER_PASSWORD';
GRANT SELECT, INSERT ON history.* TO poller_writer;
GRANT S3 ON *.* TO poller_writer;
-- Live-verified 2026-10-03: without this, the poller's INSERT INTO FUNCTION s3(...) fails with
-- ACCESS_DENIED (code 497, "necessary to have the grant CREATE TEMPORARY TABLE ON *.*") because
-- ClickHouse requires it for every table function, so the Parquet rollup never wrote.
GRANT CREATE TEMPORARY TABLE ON *.* TO poller_writer;

-- 14.2 D-04 moves the rollup (Parquet export via the s3 table function) to the analytics container,
-- so analytics_writer gets the same S3 and CREATE TEMPORARY TABLE grants (the latter is the same
-- live-verified requirement documented for poller_writer above). poller_writer keeps its S3 grants
-- for now (harmless, later cleanup). dashboard_reader and grafana_reader need no change: their
-- SELECT ON history.* already covers the new tables.
CREATE USER IF NOT EXISTS analytics_writer IDENTIFIED WITH sha256_password BY '$CH_ANALYTICS_PASSWORD';
GRANT SELECT, INSERT ON history.* TO analytics_writer;
GRANT S3 ON *.* TO analytics_writer;
GRANT CREATE TEMPORARY TABLE ON *.* TO analytics_writer;
SQL

echo "Created ClickHouse users: dashboard_reader, grafana_reader, poller_writer, analytics_writer"
