import urllib.parse
from unittest.mock import patch

import pytest

from analytics import history
from analytics.config import AnalyticsConfig


def _config():
    return AnalyticsConfig(clickhouse_url="http://ch:8123", clickhouse_writer_password="pw")


class _Resp:
    def read(self):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_insert_history_rows_posts_to_poller_table():
    captured = []

    def fake(request, timeout=None):
        captured.append(request)
        return _Resp()

    rows = [{"ts": "2026-10-14 00:00:00", "host": "h", "service": "s", "state": 0}]
    with patch("urllib.request.urlopen", side_effect=fake):
        history.insert_history_rows(_config(), "history.service_state", rows)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0].full_url).query)
    assert qs["query"][0] == "INSERT INTO history.service_state FORMAT JSONEachRow"
    assert captured[0].get_method() == "POST"


@pytest.mark.parametrize("table", ["history.events", "history.metrics; DROP"])
def test_insert_history_rows_rejects_unlisted(table):
    with patch("urllib.request.urlopen") as op:
        with pytest.raises(ValueError):
            history.insert_history_rows(_config(), table, [{"a": 1}])
    op.assert_not_called()


def test_local_insert_rows_still_refuses_poller_tables():
    with patch("urllib.request.urlopen") as op:
        with pytest.raises(ValueError):
            history.insert_rows(_config(), "history.metrics", [{"a": 1}])
    op.assert_not_called()


# --- HistoryIngest ----------------------------------------------------------

import json  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from analytics import ingest as ing  # noqa: E402

TOPIC = "app/123/dmc/history/metrics"
TS = "2026-10-14 00:00:00"
METRIC_ROW = {"ts": TS, "host": "h", "service": "s", "metric": "m", "value": 1.5, "warn": None, "crit": 9}


def _chunk(table="metrics", rows=None, event_id="E1"):
    body = {
        "event_id": event_id,
        "ts": TS,
        "table": f"history.{table}",
        "chunk": 0,
        "chunks": 1,
        "rows": [METRIC_ROW] if rows is None else rows,
    }
    return json.dumps(body).encode()


def _ingest(fail=False):
    calls = []

    def fake(config, table, rows):
        if fail:
            raise history.ClickHouseError("boom")
        calls.append((table, rows))

    cfg = AnalyticsConfig(site_sen="123", cmk_site_id="dmc", clickhouse_url="http://ch")
    return ing.HistoryIngest(cfg, insert_fn=fake), calls


def _props(event_id="E1"):
    return SimpleNamespace(UserProperty=[("event_id", event_id)])


def test_prefix_and_filter():
    assert ing.ingest_prefix("123", "dmc") == "app/123/dmc/history/"
    assert _ingest()[0].subscription_filter == "app/123/dmc/history/+"


def test_valid_chunk_inserted_once_and_duplicate_skipped():
    i, calls = _ingest()
    i.handle(TOPIC, _chunk(), _props("E"))
    i.handle(TOPIC, _chunk(), _props("E"))
    assert calls == [("history.metrics", [METRIC_ROW])]


def test_payload_event_id_fallback_and_no_key():
    i, calls = _ingest()
    i.handle(TOPIC, _chunk(event_id="P"), None)
    i.handle(TOPIC, _chunk(event_id="P"), None)
    assert len(calls) == 1
    body = json.loads(_chunk())
    del body["event_id"]
    i.handle(TOPIC, json.dumps(body).encode(), None)
    i.handle(TOPIC, json.dumps(body).encode(), None)
    assert len(calls) == 3


def test_dedupe_key_includes_topic_and_is_bounded():
    i, calls = _ingest()
    row = {"ts": TS, "host": "h", "service": "s", "state": 0}
    i.handle(TOPIC, _chunk(), _props("E"))
    i.handle("app/123/dmc/history/service_state", _chunk("service_state", [row]), _props("E"))
    assert len(calls) == 2
    for n in range(ing.SEEN_MAX + 10):
        i.handle(TOPIC, _chunk(event_id=f"x{n}"), _props(f"x{n}"))
    assert len(i._seen) == ing.SEEN_MAX


@pytest.mark.parametrize(
    "topic,payload",
    [
        ("app/999/dmc/history/metrics", _chunk()),
        ("app/123/dmc/history/events", _chunk()),
        (TOPIC, _chunk("host_state", [])),
        (TOPIC, b"{not json"),
        (TOPIC, b"[1]"),
        (TOPIC, json.dumps({"table": "history.metrics", "rows": "x"}).encode()),
        (TOPIC, b"x" * (ing.MAX_CHUNK_BYTES + 1)),
    ],
)
def test_bad_chunks_not_inserted(topic, payload):
    i, calls = _ingest()
    i.handle(topic, payload, _props())
    assert calls == []


@pytest.mark.parametrize(
    "row",
    [
        {**METRIC_ROW, "extra": 1},
        {k: v for k, v in METRIC_ROW.items() if k != "crit"},
        {**METRIC_ROW, "host": 5},
        {**METRIC_ROW, "value": True},
        {**METRIC_ROW, "value": float("nan")},
        {**METRIC_ROW, "value": None},
        {**METRIC_ROW, "ts": "2026-10-14T00:00:00"},
    ],
)
def test_invalid_row_dropped_valid_kept(row):
    i, calls = _ingest()
    i.handle(TOPIC, _chunk(rows=[row, METRIC_ROW]), _props())
    assert calls == [("history.metrics", [METRIC_ROW])]


def test_state_range_checks():
    hs = {"ts": TS, "host": "h", "folder": "f", "state": 3, "in_downtime": 0}
    assert ing.validate_rows("host_state", [hs]) == []
    assert ing.validate_rows("host_state", [{**hs, "state": 2, "in_downtime": 1}])
    ss = {"ts": TS, "host": "h", "service": "s", "state": 4}
    assert ing.validate_rows("service_state", [ss]) == []


def test_insert_failure_warns_and_allows_retry(caplog):
    i, _ = _ingest(fail=True)
    with caplog.at_level(logging.WARNING, logger="analytics.ingest"):
        i.handle(TOPIC, _chunk(), _props("E"))
    assert "Insert into history.metrics failed" in caplog.text
    assert not i._seen


class _FakeClient:
    def __init__(self):
        self.stopped = False

    def loop_start(self):
        pass

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        pass


def test_run_ingest_returns_zero_on_stop_and_never_publishes():
    client = _FakeClient()
    stop = threading.Event()
    stop.set()
    cfg = AnalyticsConfig(site_sen="123")
    assert ing.run_ingest(cfg, stop, client_factory=lambda i, c: client) == 0
    assert client.stopped
    assert not hasattr(client, "publish")


def test_ack_after_handling_via_real_client_callbacks(monkeypatch):
    import paho.mqtt.client as mqtt

    created = {}

    class Stub(mqtt.Client):
        def connect(self, *a, **k):
            created["connect"] = k

        def subscribe(self, topic, qos=0, *a, **k):
            created["sub"] = (topic, qos)

        def ack(self, mid, qos):
            created.setdefault("acks", []).append((mid, qos))

    monkeypatch.setattr(mqtt, "Client", Stub)
    i, calls = _ingest()
    client = ing.build_ingest_client(i, i.config)
    assert created["connect"]["clean_start"] is False
    assert created["connect"]["properties"].SessionExpiryInterval == 86400
    client.on_connect(client, None, None, 0, None)
    assert created["sub"] == ("app/123/dmc/history/+", 1)
    msg = SimpleNamespace(topic=TOPIC, payload=_chunk(), mid=7, qos=1, properties=_props("Z"))
    client.on_message(client, None, msg)
    client.on_message(client, None, msg)
    assert len(calls) == 1
    assert created["acks"] == [(7, 1), (7, 1)]


# --- main() dispatch --------------------------------------------------------

from analytics import service as svc  # noqa: E402


@pytest.mark.parametrize("sen", ["", "007"])
def test_main_cloud_ingest_requires_valid_sen(monkeypatch, capsys, sen):
    monkeypatch.setenv("ANALYTICS_MODE", "cloud-ingest")
    monkeypatch.setenv("SITE_SEN", sen)
    monkeypatch.setenv("CMK_SITE_ID", "dmc")
    assert svc.main() == 2
    assert "SITE_SEN" in capsys.readouterr().err


def test_main_cloud_ingest_runs_ingest_not_service(monkeypatch):
    monkeypatch.setenv("ANALYTICS_MODE", "cloud-ingest")
    monkeypatch.setenv("SITE_SEN", "123")
    monkeypatch.setenv("CMK_SITE_ID", "dmc")
    called = {}
    monkeypatch.setattr(ing, "run_ingest", lambda config, stop: called.setdefault("ok", 0))
    monkeypatch.setattr(svc.signal, "signal", lambda *a: None)
    monkeypatch.setattr(svc, "AnalyticsService", lambda *a, **k: pytest.fail("service built"))
    assert svc.main() == 0
    assert called == {"ok": 0}


def test_full_mode_input_filters_have_no_history():
    assert not any("history" in f for f in svc.INPUT_FILTERS)
