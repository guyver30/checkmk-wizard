import importlib.util
import itertools
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

# scripts/ is not an importable package -- same loading pattern as
# tests/test_provision_topology_editor.py.
_SPEC = importlib.util.spec_from_file_location(
    "seed_fake_history",
    Path(__file__).resolve().parents[1] / "scripts" / "seed_fake_history.py",
)
seed = importlib.util.module_from_spec(_SPEC)
sys.modules["seed_fake_history"] = seed
_SPEC.loader.exec_module(seed)

END_TS = 1_790_000_000  # fixed "now"
DAY = 86400


def _points(**overrides):
    kwargs = {
        "days": 60,
        "start": 60,
        "end": 84,
        "step_hours": 1,
        "noise": 0.5,
        "sawtooth_days": None,
        "seed": 42,
        "end_ts": END_TS,
    }
    kwargs.update(overrides)
    return seed.generate_points(**kwargs)


def _outcome(points, metric="fs_used_percent", warn=80.0, crit=90.0):
    return seed.expected_outcome(points, metric, warn, crit, END_TS)


# --- generation -----------------------------------------------------------------


def test_generate_points_count_and_spacing():
    pts = _points(days=10, step_hours=6, noise=0)
    assert len(pts) == 10 * 24 // 6 + 1
    assert pts[-1][0] == END_TS
    assert pts[0][0] == END_TS - 10 * DAY
    assert all(b[0] - a[0] == 6 * 3600 for a, b in itertools.pairwise(pts))


def test_generate_points_linear_without_noise_hits_start_and_end():
    pts = _points(noise=0)
    assert pts[0][1] == 60
    assert pts[-1][1] == 84
    values = [v for _, v in pts]
    assert values == sorted(values)


def test_generate_points_are_reproducible_and_seed_dependent():
    assert _points(seed=1) == _points(seed=1)
    assert _points(seed=1) != _points(seed=2)


def test_generate_points_clamped_to_0_100():
    pts = _points(start=99, end=100, noise=20)
    assert all(0 <= v <= 100 for _, v in pts)


def test_sawtooth_last_tooth_ends_at_end_and_drops_at_boundary():
    pts = _points(days=30, start=40, end=80, noise=0, sawtooth_days=10)
    assert pts[-1][1] == 80
    # a drop of about (end - start) happens at every period boundary; the very
    # first point sits at a boundary too (a tooth top), so three drops in 30 days
    drops = [a[1] - b[1] for a, b in itertools.pairwise(pts) if a[1] - b[1] > 20]
    assert len(drops) == 3
    # analytics keeps only the last tooth
    from analytics.fit import cut_after_last_sharp_drop

    kept = cut_after_last_sharp_drop(pts, seed.FIT_PARAMS)
    assert kept[0][0] > END_TS - 10 * DAY - 3600
    assert kept[0][1] < 41


def test_build_rows_shape_matches_poller_metric_rows():
    pts = [(float(END_TS), 61.23456)]
    (row,) = seed.build_rows(pts, "h1", "Filesystem /", "fs_used_percent", 80.0, 90.0)
    assert set(row) == {"ts", "host", "service", "metric", "value", "warn", "crit"}
    assert row["host"] == "h1" and row["service"] == "Filesystem /"
    assert row["metric"] == "fs_used_percent"
    assert row["warn"] == 80.0 and row["crit"] == 90.0
    assert row["ts"] == "2026-09-21 14:13:20"  # END_TS in UTC, second resolution
    assert row["value"] == 61.2346


# --- expected outcome -----------------------------------------------------------


def test_expected_outcome_defaults_urgent_medium():
    out = _outcome(_points())
    assert out["status"] == "trending"
    assert out["slope_per_day"] == pytest.approx(0.4, abs=0.02)
    assert out["days_to_crit"] == pytest.approx(15, abs=1.5)
    assert out["tier"] == "urgent"
    assert out["confidence"] == "medium"


def test_expected_outcome_immediate_when_end_close_to_crit():
    out = _outcome(_points(start=60, end=89, noise=0.2))
    assert out["status"] == "trending"
    assert out["tier"] == "immediate"


def test_expected_outcome_standard_for_far_crit():
    out = _outcome(_points(days=60, start=20, end=60, noise=0.2))
    assert out["tier"] == "standard"


def test_expected_outcome_flat_series_is_stable_without_need():
    out = _outcome(_points(start=50, end=50, noise=0))
    assert out["status"] == "stable"
    assert out["tier"] is None
    assert "stable" in out["reason"]


def test_expected_outcome_metric_outside_trend_need_set():
    out = _outcome(_points(), metric="util")
    assert out["status"] == "trending"
    assert out["tier"] is None
    assert out["reason"] == "no trend need: metric not in TREND_NEED_METRICS"


def test_expected_outcome_already_at_crit():
    out = _outcome(_points(start=80, end=95, noise=0.1))
    assert out["tier"] is None
    assert out["reason"] == (
        "no trend need: already at/above crit (a sustained need may fire instead)"
    )
    assert out["sustained"] is True


def test_expected_outcome_beyond_horizon_has_no_need():
    out = _outcome(_points(days=60, start=10, end=22, noise=0.05))
    assert out["status"] == "trending"
    assert out["tier"] is None
    assert "days to crit" in out["reason"]


# --- ClickHouse bodies ----------------------------------------------------------


def test_insert_body_is_json_each_row():
    rows = seed.build_rows(_points(days=2, noise=0), "h1", "Filesystem /", "fs_used_percent", 80, 90)
    body = seed.insert_body(rows)
    lines = body.decode("utf-8").split("\n")
    assert len(lines) == len(rows)
    assert json.loads(lines[0])["host"] == "h1"
    assert not body.endswith(b"\n")


def test_delete_sql_pins_host_service_and_metric():
    assert seed.delete_sql("demo-lnx1", "Filesystem /", "fs_used_percent") == (
        "ALTER TABLE history.metrics DELETE WHERE host = 'demo-lnx1' "
        "AND service = 'Filesystem /' AND metric = 'fs_used_percent'"
    )


class _Resp:
    def __init__(self, body=b""):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture(monkeypatch, response=None, error=None):
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        if error is not None:
            raise error
        return response or _Resp()

    monkeypatch.setattr(seed.urllib.request, "urlopen", fake_urlopen)
    return captured


def _clean_env(monkeypatch, tmp_path):
    for name in (
        "CLICKHOUSE_URL",
        "CLICKHOUSE_WRITER_USER",
        "CLICKHOUSE_WRITER_PASSWORD",
        "CH_WRITER_PASSWORD",
        "CLICKHOUSE_ADMIN_USER",
        "CH_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    return ["--env-file", str(env_file)]


def test_insert_request_url_headers_and_batching(monkeypatch, tmp_path, capsys):
    env = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CH_WRITER_PASSWORD", "s3cret")
    captured = _capture(monkeypatch)

    rc = seed.main(["--host", "demo-lnx1", "--url", "http://ch:8123/", *env], now_ts=END_TS)

    assert rc == 0
    assert len(captured) == 1441 // seed.BATCH_SIZE + 1  # 1441 rows -> one batch
    req = captured[0]
    assert req.get_method() == "POST"
    assert req.full_url == "http://ch:8123/?query=" + urllib.parse.quote(
        "INSERT INTO history.metrics FORMAT JSONEachRow"
    )
    assert req.get_header("X-clickhouse-user") == "poller_writer"
    assert req.get_header("X-clickhouse-key") == "s3cret"
    assert "s3cret" not in req.full_url
    first = json.loads(req.data.decode().split("\n")[0])
    assert first["host"] == "demo-lnx1" and first["service"] == "Filesystem /"
    assert "s3cret" not in capsys.readouterr().out


def test_insert_splits_into_batches_of_5000(monkeypatch, tmp_path):
    env = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLICKHOUSE_WRITER_PASSWORD", "pw")
    captured = _capture(monkeypatch)

    # 60 days, 0.25 h -> 5761 rows -> 2 batches
    rc = seed.main(["--host", "h", "--step-hours", "0.25", *env], now_ts=END_TS)

    assert rc == 0
    assert [len(r.data.split(b"\n")) for r in captured] == [5000, 761]


def test_delete_uses_admin_user_and_mutations_sync(monkeypatch, tmp_path, capsys):
    env = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CH_ADMIN_PASSWORD", "adminpw")
    captured = _capture(monkeypatch)

    rc = seed.main(["--host", "demo-lnx1", "--delete", "--url", "http://ch:8123", *env], now_ts=END_TS)

    assert rc == 0
    (req,) = captured
    assert req.full_url == "http://ch:8123/?mutations_sync=1"
    assert req.get_header("X-clickhouse-user") == "ch_admin"
    assert req.get_header("X-clickhouse-key") == "adminpw"
    assert req.data.decode() == (
        "ALTER TABLE history.metrics DELETE WHERE host = 'demo-lnx1' "
        "AND service = 'Filesystem /' AND metric = 'fs_used_percent'"
    )
    out = capsys.readouterr().out
    assert "clickhouse-client --user ch_admin" in out and "adminpw" not in out


def test_dry_run_makes_no_network_call(monkeypatch, tmp_path, capsys):
    env = _clean_env(monkeypatch, tmp_path)
    captured = _capture(monkeypatch)

    rc = seed.main(["--host", "demo-lnx1", "--dry-run", *env], now_ts=END_TS)

    assert rc == 0
    assert captured == []
    out = capsys.readouterr().out
    assert "trending" in out and "urgent" in out and "medium" in out
    assert "EVAL_INTERVAL_SECONDS=900" in out


def test_http_error_never_leaks_password(monkeypatch, tmp_path, capsys):
    env = _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CH_WRITER_PASSWORD", "s3cret")
    err = urllib.error.HTTPError("http://ch:8123/", 516, "auth", {}, None)
    _capture(monkeypatch, error=err)

    rc = seed.main(["--host", "h", *env], now_ts=END_TS)

    assert rc == 1
    captured = capsys.readouterr()
    assert "516" in captured.err
    assert "s3cret" not in captured.err + captured.out


def test_missing_password_exits_2_naming_the_variable(monkeypatch, tmp_path, capsys):
    env = _clean_env(monkeypatch, tmp_path)
    captured = _capture(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        seed.main(["--host", "h", *env], now_ts=END_TS)

    assert exc.value.code == 2
    assert "CH_WRITER_PASSWORD" in capsys.readouterr().err
    assert captured == []


def test_env_file_does_not_override_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('# c\nCH_WRITER_PASSWORD="fromfile"\nOTHER_SEED_VAR=x\n')
    monkeypatch.setenv("CH_WRITER_PASSWORD", "fromenv")
    monkeypatch.delenv("OTHER_SEED_VAR", raising=False)
    seed.load_env_file(env_file)
    assert seed.os.environ["CH_WRITER_PASSWORD"] == "fromenv"
    assert seed.os.environ["OTHER_SEED_VAR"] == "x"
    monkeypatch.delenv("OTHER_SEED_VAR", raising=False)


# --- argument validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--host", "bad host"],
        ["--host", "a'b"],
        ["--host", "a\\b"],
        ["--host", "h;drop"],
        ["--host", "h", "--service", "it's"],
        ["--host", "h", "--service", "a\\b"],
        ["--host", "h", "--service", "a\nb"],
        ["--host", "h", "--metric", "bad metric"],
        ["--host", "h", "--metric", "a'b"],
        ["--host", "h", "--days", "0"],
        ["--host", "h", "--days", "-3"],
        ["--host", "h", "--days", "1"],
        ["--host", "h", "--step-hours", "0"],
        ["--host", "h", "--step-hours", "25"],
        ["--host", "h", "--start", "-1"],
        ["--host", "h", "--start", "101"],
        ["--host", "h", "--end", "101"],
        ["--host", "h", "--noise", "-0.1"],
        ["--host", "h", "--warn", "90", "--crit", "90"],
        ["--host", "h", "--warn", "95", "--crit", "90"],
        ["--host", "h", "--sawtooth", "0"],
        ["--host", "h", "--sawtooth", "61"],
        ["--host", "h", "--delete", "--dry-run"],
    ],
)
def test_invalid_arguments_exit_2(argv):
    with pytest.raises(SystemExit) as exc:
        seed.parse_args(argv)
    assert exc.value.code == 2


def test_valid_arguments_parse():
    args = seed.parse_args(["--host", "demo-lnx1.example_1", "--sawtooth", "14", "--days", "60"])
    assert args.host == "demo-lnx1.example_1" and args.sawtooth == 14
