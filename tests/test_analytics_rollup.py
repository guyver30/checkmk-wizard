"""Tests for analytics.rollup: the daily availability rollup moved from the poller (D-04).

Retargeted copies of the poller's rollup tests; behaviour is unchanged.  S3 is
an in-memory fake and every ClickHouse helper is patched, so nothing here
touches the network.
"""

from __future__ import annotations

import datetime
import time
from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

from analytics import rollup
from analytics.config import AnalyticsConfig


def _make_config(**overrides) -> AnalyticsConfig:
    return AnalyticsConfig(**overrides)


# --- Availability rollups: day math and figures (Phase 14.1, D-45..D-53) ----


def test_local_day_bounds_singapore_midnight_to_midnight_utc():
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    start, end = rollup.local_day_bounds(datetime.date(2026, 9, 27), tz)
    assert start == datetime.datetime(2026, 9, 26, 16, 0, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 9, 27, 16, 0, tzinfo=datetime.UTC)
    assert start.tzinfo is not None and end.tzinfo is not None


def test_rollup_days_to_check_ascending_within_backfill_window():
    days = rollup.rollup_days_to_check(
        today_local=datetime.date(2026, 9, 28),
        first_data_day=datetime.date(2026, 9, 20),
        backfill_days=28,
    )
    assert days == [datetime.date(2026, 9, 20) + datetime.timedelta(days=i) for i in range(8)]


def test_rollup_days_to_check_no_first_data_day_returns_empty():
    assert rollup.rollup_days_to_check(datetime.date(2026, 9, 28), None, 28) == []


def test_rollup_days_to_check_first_data_day_today_returns_empty():
    today = datetime.date(2026, 9, 28)
    assert rollup.rollup_days_to_check(today, today, 28) == []


def test_rollup_days_to_check_first_data_day_far_in_past_clamps_to_backfill_window():
    today = datetime.date(2026, 9, 28)
    first = today - datetime.timedelta(days=60)
    days = rollup.rollup_days_to_check(today, first, 28)
    assert len(days) == 28
    assert days[0] == today - datetime.timedelta(days=28)
    assert days[-1] == today - datetime.timedelta(days=1)


def test_rollup_object_keys_hive_style_parquet_prefix():
    json_key, parquet_key = rollup.rollup_object_keys(datetime.date(2026, 9, 7))
    assert json_key == "availability/2026/09/2026-09-07.json"
    assert parquet_key == "availability_parquet/date=2026-09-07/availability.parquet"


def _host_row(host="h1", folder="", **counts):
    row = {"host": host, "folder": folder, "up_samples": 0, "down_samples": 0,
           "unreach_samples": 0, "downtime_samples": 0}
    row.update(counts)
    return row


def _device_row(rows, host="h1"):
    return next(r for r in rows if r["entity_type"] == "device" and r["entity_key"] == host)


def _fleet_row(rows):
    return next(r for r in rows if r["group_type"] == "fleet")


def test_compute_daily_availability_all_up_day():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=5760)], 15
    )
    device = _device_row(rows)
    assert device["up_minutes"] == 1440
    assert device["up_pct"] == 100
    assert device["availability_pct"] == 100
    assert device["no_data_minutes"] == 0


def test_compute_daily_availability_half_up_half_down():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, down_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 50
    assert device["up_pct"] == 50
    assert device["down_pct"] == 50


def test_compute_daily_availability_unreachable_excluded_from_availability():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, unreach_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 100
    assert device["unobserved_pct"] == 50


def test_compute_daily_availability_downtime_excluded_from_availability():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, downtime_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 100
    assert device["downtime_minutes"] == 720
    assert device["downtime_pct"] == 50


def test_compute_daily_availability_partial_samples_report_no_data():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["no_data_minutes"] == 720
    assert device["no_data_pct"] == 50
    assert device["availability_pct"] == 100


def test_compute_daily_availability_zero_samples_is_all_no_data():
    rows = rollup.compute_daily_availability(datetime.date(2026, 9, 27), [_host_row()], 15)
    device = _device_row(rows)
    assert device["no_data_pct"] == 100
    assert device["availability_pct"] is None


def test_compute_daily_availability_more_samples_than_a_day_holds():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=10000)], 15
    )
    device = _device_row(rows)
    assert device["no_data_minutes"] == 0
    total_pct = (
        device["up_pct"] + device["down_pct"] + device["unobserved_pct"]
        + device["downtime_pct"] + device["no_data_pct"]
    )
    assert total_pct == pytest.approx(100, abs=0.01)


def test_compute_daily_availability_folder_row_sums_two_hosts():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27),
        [
            _host_row(host="a", folder="/servers", up_samples=5760),
            _host_row(host="b", folder="/servers", up_samples=2880, down_samples=2880),
        ],
        15,
    )
    folder_row = next(r for r in rows if r["group_type"] == "folder")
    assert folder_row["entity_key"] == "/servers"
    assert folder_row["device_count"] == 2
    assert folder_row["up_minutes"] == 1440 + 720
    assert folder_row["down_minutes"] == 720
    assert folder_row["availability_pct"] == pytest.approx(
        (1440 + 720) / (1440 + 720 + 720) * 100, abs=0.01
    )


def test_compute_daily_availability_empty_folder_grouped_under_no_folder_key():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", folder="", up_samples=5760)], 15
    )
    folder_row = next(r for r in rows if r["group_type"] == "folder")
    assert folder_row["entity_key"] == rollup.FOLDERLESS_GROUP_KEY


def test_compute_daily_availability_fleet_row_always_present_and_last():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", up_samples=5760)], 15
    )
    assert rows[-1]["group_type"] == "fleet"
    assert rows[-1]["entity_key"] == rollup.FLEET_GROUP_KEY


def test_compute_daily_availability_empty_host_list_yields_only_fleet_row():
    rows = rollup.compute_daily_availability(datetime.date(2026, 9, 27), [], 15)
    assert len(rows) == 1
    fleet = rows[0]
    assert fleet["group_type"] == "fleet"
    assert fleet["device_count"] == 0
    assert fleet["no_data_pct"] == 100
    assert fleet["availability_pct"] is None


def test_compute_daily_availability_string_sample_counts_accepted():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples="5760")], 15
    )
    assert _device_row(rows)["up_minutes"] == 1440


def test_compute_daily_availability_devices_before_folders_before_fleet():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27),
        [_host_row(host="a", folder="/x", up_samples=5760)],
        15,
    )
    kinds = [(r["entity_type"], r["group_type"]) for r in rows]
    assert kinds == [("device", ""), ("group", "folder"), ("group", "fleet")]


def test_availability_document_shape_matches_schema():
    rows = rollup.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", folder="/x", up_samples=5760)], 15
    )
    doc = rollup.availability_document(
        datetime.date(2026, 9, 27),
        rows,
        timezone_name="Asia/Singapore",
        poll_interval_seconds=15,
        generated_at_iso="2026-09-28T00:05:00+00:00",
    )
    assert doc["schema_version"] == rollup.AVAILABILITY_SCHEMA_VERSION
    assert doc["date"] == "2026-09-27"
    assert doc["timezone"] == "Asia/Singapore"
    assert doc["poll_interval_seconds"] == 15
    assert doc["generated_at"] == "2026-09-28T00:05:00+00:00"
    assert len(doc["devices"]) == 1
    assert doc["devices"][0]["host"] == "a"
    assert len(doc["groups"]) == 2
    assert rollup.availability_document_problems(doc) == []


def test_availability_document_problems_detects_wrong_schema_version():
    doc = {"schema_version": 99, "date": "2026-09-27", "devices": [], "groups": []}
    assert rollup.availability_document_problems(doc) != []


def test_availability_document_problems_detects_bad_date():
    doc = {"schema_version": rollup.AVAILABILITY_SCHEMA_VERSION, "date": "not-a-date",
           "devices": [], "groups": []}
    assert rollup.availability_document_problems(doc) != []


def test_availability_document_problems_detects_pct_out_of_range():
    doc = {
        "schema_version": rollup.AVAILABILITY_SCHEMA_VERSION,
        "date": "2026-09-27",
        "devices": [{"up_pct": 150, "down_pct": 0, "unobserved_pct": 0, "downtime_pct": 0,
                     "no_data_pct": 0, "availability_pct": None}],
        "groups": [],
    }
    assert rollup.availability_document_problems(doc) != []


def test_availability_document_problems_detects_non_numeric_figure():
    doc = {
        "schema_version": rollup.AVAILABILITY_SCHEMA_VERSION,
        "date": "2026-09-27",
        "devices": [{"up_pct": "100", "down_pct": 0, "unobserved_pct": 0, "downtime_pct": 0,
                     "no_data_pct": 0, "availability_pct": None}],
        "groups": [],
    }
    assert rollup.availability_document_problems(doc) != []


# --- Availability rollups: S3 writer, ClickHouse fetch, JSON+Parquet (Phase 14.1) ---


def _client_error(code: str):
    return botocore.exceptions.ClientError({"Error": {"Code": code}}, "HeadObject")


class _FakeS3:
    """Minimal in-memory S3 fake (head_object/put_object only) -- no moto, per PATTERNS.md."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _client_error("404")

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = Body


def test_write_if_absent_first_call_puts_and_returns_true():
    s3 = _FakeS3()
    result = rollup.write_if_absent(s3, "bucket", "key.json", b"hello", "application/json")
    assert result is True
    assert s3.objects[("bucket", "key.json")] == b"hello"


def test_write_if_absent_second_call_returns_false_and_leaves_bytes_unchanged():
    s3 = _FakeS3()
    rollup.write_if_absent(s3, "bucket", "key.json", b"hello", "application/json")
    result = rollup.write_if_absent(s3, "bucket", "key.json", b"changed", "application/json")
    assert result is False
    assert s3.objects[("bucket", "key.json")] == b"hello"


def test_write_if_absent_head_error_other_than_404_reraises():
    class _BrokenS3(_FakeS3):
        def head_object(self, Bucket, Key):
            raise _client_error("403")

    with pytest.raises(botocore.exceptions.ClientError):
        rollup.write_if_absent(_BrokenS3(), "bucket", "key.json", b"hello", "application/json")


def _rollup_config(**overrides) -> AnalyticsConfig:
    defaults = {
        "clickhouse_url": "http://clickhouse:8123",
        "clickhouse_writer_user": "analytics_writer",
        "clickhouse_writer_password": "secret",
        "s3_endpoint": "http://minio:9000",
        "s3_access_key": "minioadmin",
        "s3_secret_key": "minioadmin",
        "availability_bucket": "fleet-availability",
        "rollup_tz": "Asia/Singapore",
    }
    defaults.update(overrides)
    return _make_config(**defaults)


def test_rollup_one_day_both_keys_present_returns_skipped_and_makes_no_clickhouse_call():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, parquet_key = rollup.rollup_object_keys(day)
    s3.objects[("fleet-availability", json_key)] = b"{}"
    s3.objects[("fleet-availability", parquet_key)] = b"parquet"
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "_clickhouse_query") as mock_query,
        patch.object(rollup, "_insert_availability_rows") as mock_insert,
        patch.object(rollup, "_clickhouse_command") as mock_command,
    ):
        result = rollup.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "skipped"
    mock_query.assert_not_called()
    mock_insert.assert_not_called()
    mock_command.assert_not_called()


def test_rollup_one_day_writes_json_and_parquet_when_neither_exists():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    start_utc, end_utc = rollup.local_day_bounds(day, tz)
    host_row = {
        "host": "a",
        "folder": "",
        "up_samples": "5760",
        "down_samples": "0",
        "unreach_samples": "0",
        "downtime_samples": "0",
    }
    with (
        patch.object(rollup, "_clickhouse_query", return_value=[host_row]) as mock_query,
        patch.object(rollup, "_insert_availability_rows") as mock_insert,
        patch.object(rollup, "_clickhouse_command") as mock_command,
    ):
        result = rollup.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    called_sql = mock_query.call_args.args[3]
    assert start_utc.strftime("%Y-%m-%d %H:%M:%S") in called_sql
    assert end_utc.strftime("%Y-%m-%d %H:%M:%S") in called_sql
    assert mock_insert.call_args.args[3] == "history.availability_daily"
    command_sql = mock_command.call_args.args[3]
    json_key, parquet_key = rollup.rollup_object_keys(day)
    assert "INSERT INTO FUNCTION s3(" in command_sql
    assert parquet_key in command_sql
    assert "fleet-availability" in command_sql
    assert "'Parquet'" in command_sql
    assert "FROM history.availability_daily FINAL WHERE day = " in command_sql
    assert ("fleet-availability", json_key) in s3.objects


def test_rollup_one_day_only_json_present_runs_parquet_export_only():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, _parquet_key = rollup.rollup_object_keys(day)
    s3.objects[("fleet-availability", json_key)] = b"{}"
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "_clickhouse_query", return_value=[]),
        patch.object(rollup, "_insert_availability_rows"),
        patch.object(rollup, "_clickhouse_command") as mock_command,
    ):
        result = rollup.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    mock_command.assert_called_once()
    assert s3.objects[("fleet-availability", json_key)] == b"{}"


def test_rollup_one_day_only_parquet_present_runs_json_put_only():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, parquet_key = rollup.rollup_object_keys(day)
    s3.objects[("fleet-availability", parquet_key)] = b"parquet-bytes"
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "_clickhouse_query", return_value=[]),
        patch.object(rollup, "_insert_availability_rows"),
        patch.object(rollup, "_clickhouse_command") as mock_command,
    ):
        result = rollup.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    mock_command.assert_not_called()
    assert ("fleet-availability", json_key) in s3.objects
    assert s3.objects[("fleet-availability", parquet_key)] == b"parquet-bytes"


def test_rollup_one_day_invalid_document_raises_rollup_error_and_nothing_is_put():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, parquet_key = rollup.rollup_object_keys(day)
    s3.objects[("fleet-availability", parquet_key)] = b"parquet-bytes"
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "_clickhouse_query", return_value=[]),
        patch.object(rollup, "_insert_availability_rows"),
        patch.object(rollup, "availability_document_problems", return_value=["bad schema_version"]),
        pytest.raises(rollup.RollupError),
    ):
        rollup.rollup_one_day(_rollup_config(), s3, tz, day)
    assert ("fleet-availability", json_key) not in s3.objects


def test_export_parquet_access_key_with_quote_raises_without_request():
    config = _rollup_config(s3_access_key="bad'key")
    parquet_key = "availability_parquet/date=2026-09-27/availability.parquet"
    with (
        patch.object(rollup, "_clickhouse_command") as mock_command,
        pytest.raises(rollup.ClickHouseError),
    ):
        rollup.export_parquet(config, datetime.date(2026, 9, 27), parquet_key)
    mock_command.assert_not_called()


def test_export_parquet_secret_key_with_quote_raises_without_request():
    config = _rollup_config(s3_secret_key="bad'secret")
    parquet_key = "availability_parquet/date=2026-09-27/availability.parquet"
    with (
        patch.object(rollup, "_clickhouse_command") as mock_command,
        pytest.raises(rollup.ClickHouseError),
    ):
        rollup.export_parquet(config, datetime.date(2026, 9, 27), parquet_key)
    mock_command.assert_not_called()


def test_run_rollups_continues_past_a_failing_day():
    config = _rollup_config()
    s3 = _FakeS3()
    with (
        patch.object(rollup, "fetch_first_data_day", return_value=datetime.date(2026, 9, 20)),
        patch.object(
            rollup,
            "rollup_one_day",
            side_effect=[rollup.RollupError("boom"), "written", "skipped"],
        ),
    ):
        written, failures = rollup.run_rollups(config, s3, datetime.date(2026, 9, 23))
    assert failures == 1
    assert len(written) == 1


def test_fetch_first_data_day_returns_none_when_table_empty():
    config = _rollup_config()
    with patch.object(rollup, "_clickhouse_query", return_value=[{"d": "1970-01-01", "n": "0"}]):
        assert rollup.fetch_first_data_day(config, "Asia/Singapore") is None


def test_fetch_first_data_day_returns_date_when_table_has_rows():
    config = _rollup_config()
    with patch.object(rollup, "_clickhouse_query", return_value=[{"d": "2026-09-20", "n": "1000"}]):
        assert rollup.fetch_first_data_day(config, "Asia/Singapore") == datetime.date(2026, 9, 20)



# --- RollupScheduler / maybe_run_rollups (Phase 14.1, D-49/D-51/D-52) --------


def test_rollup_scheduler_fresh_instance_is_due_immediately_regardless_of_time():
    scheduler = rollup.RollupScheduler()
    now_local = datetime.datetime(2026, 9, 28, 13, 0, tzinfo=datetime.UTC)
    assert scheduler.due(now_local, now_monotonic=0.0) is True
    assert scheduler.due(now_local, now_monotonic=99999.0) is True


def test_rollup_scheduler_not_due_again_same_day_after_success():
    scheduler = rollup.RollupScheduler()
    scheduler.mark_success(datetime.date(2026, 9, 28))
    for hour in (0, 12, 23):
        now_local = datetime.datetime(2026, 9, 28, hour, 0, tzinfo=datetime.UTC)
        assert scheduler.due(now_local, now_monotonic=0.0) is False


def test_rollup_scheduler_due_after_midnight_delay_on_the_next_day():
    scheduler = rollup.RollupScheduler(delay_minutes=5)
    scheduler.mark_success(datetime.date(2026, 9, 28))
    before_delay = datetime.datetime(2026, 9, 29, 0, 3, tzinfo=datetime.UTC)
    after_delay = datetime.datetime(2026, 9, 29, 0, 5, tzinfo=datetime.UTC)
    assert scheduler.due(before_delay, now_monotonic=0.0) is False
    assert scheduler.due(after_delay, now_monotonic=0.0) is True


def test_rollup_scheduler_mark_failure_backs_off_then_retries():
    scheduler = rollup.RollupScheduler()
    scheduler.mark_failure(now_monotonic=1000.0)
    now_local = datetime.datetime(2026, 9, 28, 13, 0, tzinfo=datetime.UTC)
    assert scheduler.due(now_local, now_monotonic=1200.0) is False
    assert scheduler.due(now_local, now_monotonic=1300.0) is True


def test_maybe_run_rollups_noop_when_clickhouse_url_unset():
    config = _make_config(clickhouse_url="", s3_endpoint="http://minio:9000")
    scheduler = rollup.RollupScheduler()
    s3_holder: dict = {}
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "build_s3_client") as mock_build,
        patch.object(rollup, "run_rollups") as mock_run,
    ):
        rollup.maybe_run_rollups(
            config, scheduler, s3_holder, tz, datetime.datetime.now(tz), time.monotonic()
        )
    mock_build.assert_not_called()
    mock_run.assert_not_called()
    assert s3_holder == {}


def test_maybe_run_rollups_noop_when_s3_endpoint_unset():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="")
    scheduler = rollup.RollupScheduler()
    s3_holder: dict = {}
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(rollup, "build_s3_client") as mock_build,
        patch.object(rollup, "run_rollups") as mock_run,
    ):
        rollup.maybe_run_rollups(
            config, scheduler, s3_holder, tz, datetime.datetime.now(tz), time.monotonic()
        )
    mock_build.assert_not_called()
    mock_run.assert_not_called()


def test_maybe_run_rollups_marks_success_when_zero_failures():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = rollup.RollupScheduler()
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        patch.object(rollup, "build_s3_client", return_value=MagicMock()),
        patch.object(rollup, "run_rollups", return_value=([], 0)),
    ):
        rollup.maybe_run_rollups(config, scheduler, {}, tz, now_local, time.monotonic())
    assert scheduler.last_completed_local_date == now_local.date()


def test_maybe_run_rollups_marks_failure_when_run_rollups_reports_failures():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = rollup.RollupScheduler()
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        patch.object(rollup, "build_s3_client", return_value=MagicMock()),
        patch.object(rollup, "run_rollups", return_value=([], 2)),
    ):
        rollup.maybe_run_rollups(config, scheduler, {}, tz, now_local, time.monotonic())
    assert scheduler.last_completed_local_date is None
    assert scheduler.next_attempt_monotonic > 0.0


def test_maybe_run_rollups_logs_and_marks_failure_instead_of_raising(caplog):
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = rollup.RollupScheduler()
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        caplog.at_level("WARNING", logger=rollup._logger.name),
        patch.object(rollup, "build_s3_client", return_value=MagicMock()),
        patch.object(rollup, "run_rollups", side_effect=rollup.ClickHouseError("boom")),
    ):
        rollup.maybe_run_rollups(config, scheduler, {}, tz, now_local, time.monotonic())
    assert scheduler.last_completed_local_date is None
    assert scheduler.next_attempt_monotonic > 0.0
    assert any("Availability rollup run failed" in record.getMessage() for record in caplog.records)


def test_maybe_run_rollups_reuses_s3_client_across_calls():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = rollup.RollupScheduler()
    tz = rollup.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    s3_holder: dict = {}
    with (
        patch.object(rollup, "build_s3_client", return_value=MagicMock()) as mock_build,
        patch.object(rollup, "run_rollups", return_value=([], 0)),
    ):
        rollup.maybe_run_rollups(config, scheduler, s3_holder, tz, now_local, time.monotonic())
        scheduler.next_attempt_monotonic = 0.0
        scheduler.last_completed_local_date = None
        rollup.maybe_run_rollups(config, scheduler, s3_holder, tz, now_local, time.monotonic())
    mock_build.assert_called_once()


def test_insert_availability_rows_unlisted_table_raises_without_a_request():
    # The local allowlist is the only thing keeping an arbitrary table name out
    # of the INSERT statement's SQL text (no parameterized identifiers over HTTP).
    with (
        patch.object(rollup, "_clickhouse_request") as mock_request,
        pytest.raises(rollup.ClickHouseError),
    ):
        rollup._insert_availability_rows(
            "http://clickhouse:8123", "u", "p", "history.events", [{"a": 1}], 5.0
        )
    mock_request.assert_not_called()


def test_insert_availability_rows_posts_one_json_each_row_batch():
    with patch.object(rollup, "_clickhouse_request") as mock_request:
        rollup._insert_availability_rows(
            "http://clickhouse:8123", "u", "p", "history.availability_daily", [{"a": 1}], 5.0
        )
    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["data"] == b'{"a": 1}'
    assert "INSERT%20INTO%20history.availability_daily" in mock_request.call_args.args[0]
