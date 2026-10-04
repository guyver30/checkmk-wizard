"""Tests for analytics.fit: trend gate, sharp-drop cut, crossing dates."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime

import pytest

from analytics import fit

DAY = 86400.0
BUCKET = 6 * 3600.0
START_TS = 1_700_000_000.0
PARAMS = fit.FitParams()


def ramp(
    v0: float,
    v1: float,
    days: float,
    start_ts: float = START_TS,
) -> list[tuple[float, float]]:
    n = int(days * DAY / BUCKET) + 1
    return [
        (start_ts + i * BUCKET, v0 + (v1 - v0) * i / (n - 1)) for i in range(n)
    ]


def noise_series(days: float = 30) -> list[tuple[float, float]]:
    rng = random.Random(1)
    n = int(days * DAY / BUCKET) + 1
    return [(START_TS + i * BUCKET, rng.uniform(40, 60)) for i in range(n)]


def now_after(points: list[tuple[float, float]]) -> float:
    return points[-1][0] + 3600.0


def test_steady_ramp_is_trending_with_exact_crossings():
    pts = ramp(50, 80, 30)
    now = now_after(pts)
    f = fit.fit_series(pts, warn=85, crit=90, params=PARAMS, now_ts=now)
    assert f.status == "trending"
    assert f.slope_per_day == pytest.approx(1.0, rel=1e-6)
    assert f.value_at_end == pts[-1][1]
    assert f.fit_end_ts == pts[-1][0]
    # D-15: same formula the browser uses, anchored on the published values.
    expected = f.fit_end_ts + (90 - f.value_at_end) / f.slope_per_day * 86400
    assert f.crit_ts == expected
    assert f.crit_date == datetime.fromtimestamp(expected, UTC).strftime("%Y-%m-%d")
    assert f.days_to_crit == pytest.approx((f.crit_ts - now) / 86400)
    assert f.warn_ts is not None and f.warn_ts < f.crit_ts
    assert f.confidence == "medium"
    assert f.history_days == pytest.approx(30.0)


def test_confidence_low_for_short_history():
    pts = ramp(50, 60, 10)
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.confidence == "low"


def test_confidence_high_needs_long_history_and_high_r2():
    pts = ramp(10, 90, 80)
    f = fit.fit_series(pts, 95, 99, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.r2 >= 0.90
    assert f.confidence == "high"


def test_confidence_thresholds():
    # D-10: over 60 days is only high with r2 >= 0.90.
    assert fit.confidence_for(80.0, 0.75, PARAMS) == "medium"
    assert fit.confidence_for(80.0, 0.95, PARAMS) == "high"
    assert fit.confidence_for(13.9, 0.99, PARAMS) == "low"
    assert fit.confidence_for(14.0, 0.99, PARAMS) == "medium"
    assert fit.confidence_for(60.0, 0.99, PARAMS) == "medium"


def test_history_days_is_available_history_not_fit_window():
    # D-10: 80 days of input, cleanup 5 days ago -> fit window is 5 days but
    # history_days stays 80.
    before = ramp(40, 80, 75)
    after = ramp(45, 50, 5, start_ts=before[-1][0] + BUCKET)
    pts = before + after
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.history_days == pytest.approx((pts[-1][0] - pts[0][0]) / DAY)
    assert f.history_days > 79
    assert f.fit_start_ts == after[0][0]
    assert f.fit_end_ts - f.fit_start_ts < 6 * DAY


def test_noise_is_no_clear_trend():
    # Pitfall 1: OLS always returns a slope; the r2 gate must refuse noise.
    pts = noise_series()
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "no_clear_trend"
    assert f.slope_per_day is None
    assert f.confidence is None
    assert f.crit_ts is None and f.warn_ts is None
    assert f.crit_date is None and f.days_to_crit is None
    assert f.history_days == pytest.approx(30.0)


def test_constant_series_is_stable_without_error():
    # correlation() raises StatisticsError on zero variance.
    pts = [(START_TS + i * BUCKET, 42.0) for i in range(40)]
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "stable"
    assert f.slope_per_day is None and f.crit_ts is None


def test_falling_ramp_is_stable():
    pts = ramp(80, 50, 30)
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "stable"
    assert f.slope_per_day is None and f.crit_date is None


def test_rise_below_floor_is_stable():
    pts = ramp(50, 50.3, 30)
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "stable"


def test_cleanup_drop_is_cut_so_it_does_not_bend_trend():
    # Pitfall 2: one disk cleanup must not flatten the fit.
    up = ramp(40, 80, 20)
    after = ramp(45, 60, 15, start_ts=up[-1][0] + BUCKET)
    pts = up + after
    assert fit.cut_after_last_sharp_drop(pts, PARAMS) == after
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.fit_start_ts == after[0][0]
    assert f.slope_per_day == pytest.approx(1.0, rel=1e-6)


def test_small_wobble_is_not_a_sharp_drop():
    # Drop of 2 with range 10: threshold = max(5, 0.25 * 10) = 5.
    pts = [(START_TS + i * BUCKET, v) for i, v in enumerate([85, 90, 88, 90, 95])]
    assert fit.cut_after_last_sharp_drop(pts, PARAMS) == pts


def test_too_few_points_or_span_is_no_clear_trend():
    few = ramp(50, 60, 1)  # 5 buckets, 1 day
    f = fit.fit_series(few, 85, 90, PARAMS, now_after(few))
    assert f.status == "no_clear_trend"
    # A drop that leaves only a handful of buckets must not date anything.
    up = ramp(40, 80, 20)
    tail = [(up[-1][0] + BUCKET * (i + 1), 45 + i) for i in range(3)]
    f2 = fit.fit_series(up + tail, 85, 90, PARAMS, tail[-1][0] + 1)
    assert f2.status == "no_clear_trend"
    assert f2.history_days > 19


def test_empty_input_is_no_clear_trend():
    f = fit.fit_series([], 85, 90, PARAMS, START_TS)
    assert f.status == "no_clear_trend"
    assert f.history_days == 0.0


def test_non_finite_points_are_dropped():
    pts = ramp(50, 80, 30)
    dirty = pts[:5] + [(pts[5][0], math.nan), (pts[6][0], math.inf)] + pts[7:]
    f = fit.fit_series(dirty, 85, 90, PARAMS, now_after(pts))
    assert f.status == "trending"


def test_already_over_level_has_no_future_crossing():
    pts = ramp(70, 92, 22)
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.crit_ts is None and f.crit_date is None
    assert f.days_to_crit == 0.0
    assert f.warn_ts is None and f.days_to_warn == 0.0


def test_missing_level_leaves_crossing_none():
    pts = ramp(50, 80, 30)
    f = fit.fit_series(pts, None, 90, PARAMS, now_after(pts))
    assert f.warn_ts is None and f.warn_date is None and f.days_to_warn is None
    assert f.crit_ts is not None


def test_inverted_levels_skip_crossings():
    pts = ramp(50, 80, 30)
    f = fit.fit_series(pts, 90, 85, PARAMS, now_after(pts))
    assert f.status == "trending"
    assert f.crit_ts is None and f.warn_ts is None
    assert f.days_to_crit is None and f.days_to_warn is None


def test_to_payload_is_json_safe():
    pts = ramp(50, 80, 30)
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    payload = f.to_payload("Filesystem /", "fs_used_percent", "%")
    json.dumps(payload)
    assert payload["service"] == "Filesystem /"
    assert payload["metric"] == "fs_used_percent"
    assert payload["unit"] == "%"
    assert payload["status"] == "trending"
    assert payload["crit_date"] == f.crit_date


def test_payload_for_noise_has_no_drawing_fields():
    pts = noise_series()
    f = fit.fit_series(pts, 85, 90, PARAMS, now_after(pts))
    payload = f.to_payload("CPU utilization", "util", "%")
    assert payload["status"] == "no_clear_trend"
    assert payload["slope_per_day"] is None
    assert payload["value_at_end"] is None
