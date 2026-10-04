import io
import urllib.error
import urllib.parse
from unittest.mock import patch

import pytest

from analytics import history
from analytics.config import AnalyticsConfig

USER = "analytics_writer"
PASSWORD = "s3cr3t-pw"


def _config():
    return AnalyticsConfig(
        clickhouse_url="http://ch:8123",
        clickhouse_writer_user=USER,
        clickhouse_writer_password=PASSWORD,
    )


class _Resp:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(fn, body="", *args, **kwargs):
    """Call fn with urlopen patched; return (result, captured Request list)."""
    captured = []

    def fake(request, timeout=None):
        captured.append(request)
        return _Resp(body)

    with patch("urllib.request.urlopen", side_effect=fake):
        result = fn(*args, **kwargs)
    return result, captured


def _sql(request) -> str:
    qs = urllib.parse.urlparse(request.full_url).query
    return urllib.parse.parse_qs(qs)["query"][0]


def test_request_uses_headers_not_url():
    _, reqs = _run(history._query, "", _config(), "SELECT 1")
    req = reqs[0]
    assert req.get_method() == "GET"
    assert req.get_header("X-clickhouse-user") == USER
    assert req.get_header("X-clickhouse-key") == PASSWORD
    assert USER not in req.full_url and PASSWORD not in req.full_url
    assert _sql(req).endswith("FORMAT JSONEachRow")


def test_errors_become_clickhouse_error_without_password():
    err = urllib.error.HTTPError("http://ch", 500, "x", {}, io.BytesIO(b"boom"))
    with patch("urllib.request.urlopen", side_effect=err), pytest.raises(
        history.ClickHouseError
    ) as exc:
        history._query(_config(), "SELECT 1")
    assert "HTTP 500" in str(exc.value) and PASSWORD not in str(exc.value)
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
    ), pytest.raises(history.ClickHouseError) as exc:
        history._query(_config(), "SELECT 1")
    assert PASSWORD not in str(exc.value)


def test_fetch_fit_buckets_sql_and_result():
    body = (
        '{"host":"h","service":"Filesystem /","metric":"fs_used_percent","t":200,"v":2.0}\n'
        '{"host":"h","service":"Filesystem /","metric":"fs_used_percent","t":100,"v":1.0}\n'
        '{"host":"h","service":"Memory","metric":"mem_used_percent","t":"100","v":null}\n'
    )
    result, reqs = _run(
        history.fetch_fit_buckets, body, _config(), ["fs_used_percent", "mem_used_percent"]
    )
    sql = _sql(reqs[0])
    assert "sum(value_sum) / sum(value_count)" in sql
    assert "toStartOfInterval(ts, INTERVAL 6 HOUR)" in sql
    assert "INTERVAL 90 DAY" in sql
    assert "metric IN ('fs_used_percent', 'mem_used_percent')" in sql
    assert result == {("h", "Filesystem /", "fs_used_percent"): [(100, 1.0), (200, 2.0)]}


def test_fetch_levels_preserves_none():
    body = (
        '{"host":"h","service":"Memory","metric":"mem_used_percent","warn":80,"crit":90}\n'
        '{"host":"h","service":"CPU utilization","metric":"util","warn":null,"crit":null}\n'
    )
    result, reqs = _run(history.fetch_levels, body, _config(), ["mem_used_percent", "util"])
    sql = _sql(reqs[0])
    assert "argMax(warn, ts)" in sql and "argMax(crit, ts)" in sql and "INTERVAL 2 DAY" in sql
    assert result[("h", "Memory", "mem_used_percent")] == (80.0, 90.0)
    assert result[("h", "CPU utilization", "util")] == (None, None)


def test_fetch_recent_hourly():
    body = '{"host":"h","service":"s","metric":"util","t":3600,"v":5.5}\n'
    result, reqs = _run(history.fetch_recent_hourly, body, _config(), ["util"], 24)
    assert "INTERVAL 24 HOUR" in _sql(reqs[0])
    assert result == {("h", "s", "util"): [(3600, 5.5)]}


@pytest.mark.parametrize("bad", ["a'b", "a b", "", "x" * 65, "a;DROP"])
def test_bad_metric_name_rejected_before_request(bad):
    with patch("urllib.request.urlopen") as op:
        for fn in (history.fetch_fit_buckets, history.fetch_levels):
            with pytest.raises(ValueError):
                fn(_config(), ["ok_metric", bad])
        with pytest.raises(ValueError):
            history.fetch_recent_hourly(_config(), [bad], 24)
    op.assert_not_called()


def test_insert_rows_posts_json_lines():
    rows = [{"ts": "2026-10-04 00:00:00", "device_id": "a"}, {"ts": "2026-10-04 00:00:01", "device_id": "b"}]
    _, reqs = _run(history.insert_rows, "", _config(), "history.events", rows)
    req = reqs[0]
    assert req.get_method() == "POST"
    assert _sql(req) == "INSERT INTO history.events FORMAT JSONEachRow"
    assert req.data.decode().splitlines() == [
        '{"ts": "2026-10-04 00:00:00", "device_id": "a"}',
        '{"ts": "2026-10-04 00:00:01", "device_id": "b"}',
    ]


def test_insert_rows_rejects_other_tables_and_empty_is_noop():
    with patch("urllib.request.urlopen") as op:
        with pytest.raises(ValueError):
            history.insert_rows(_config(), "history.metrics", [{"a": 1}])
        history.insert_rows(_config(), "history.events", [])
    op.assert_not_called()


def test_missing_tables_subset():
    body = '{"name":"events"}\n{"name":"incidents"}\n'
    result, reqs = _run(history.missing_tables, body, _config())
    assert result == {"history.need_triage"}
    assert "system.tables" in _sql(reqs[0]) and "database = 'history'" in _sql(reqs[0])


def test_missing_tables_on_error_returns_all_without_raise():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("denied")):
        assert history.missing_tables(_config()) == set(history.ANALYTICS_TABLES)


def test_fetch_open_incidents_final_and_int_conversion():
    body = '{"incident_id":"incident-sw1","status":"open","duration_s":"12","inferred":"1"}\n'
    result, reqs = _run(history.fetch_open_incidents, body, _config())
    sql = _sql(reqs[0])
    assert "history.incidents FINAL" in sql and "status = 'open'" in sql
    assert result[0]["duration_s"] == 12 and result[0]["inferred"] == 1


def test_fetch_recent_event_keys():
    body = (
        '{"ts_iso":"2026-10-04 00:00:00","device_id":"a","event":"state_change",'
        '"from_state":"UP","to_state":"DOWN"}\n'
    )
    result, reqs = _run(history.fetch_recent_event_keys, body, _config(), 2)
    assert "history.events" in _sql(reqs[0]) and "INTERVAL 2 DAY" in _sql(reqs[0])
    assert result == {("2026-10-04 00:00:00", "a", "state_change", "UP", "DOWN")}


def test_malformed_response_raises():
    with patch("urllib.request.urlopen", return_value=_Resp("not json")), pytest.raises(
        history.ClickHouseError
    ):
        history._query(_config(), "SELECT 1")
