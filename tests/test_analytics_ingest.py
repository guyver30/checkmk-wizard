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
