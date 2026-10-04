"""Trend fit for chartable metric series (D-10, D-11, D-15, D-19a).

Every forecast, every trend need and the chart's dashed line come from
`fit_series`, so its quality gate is the "no clear trend" rule: a series that
does not rise in a straight line gets no slope, no date and nothing to draw.

Algorithm (14.2-RESEARCH "Fit algorithm"): cut the series after its last sharp
drop (a disk cleanup or reboot must not bend the trend), require enough
buckets and span, run an ordinary least squares fit, then gate on r2 and on a
minimum rise per 30 days. "Higher is worse" for every metric.

The browser never refits (D-15). The published anchor is
(`fit_end_ts`, `value_at_end`) where `value_at_end` is the last actual bucket
value, so a chart draws

    y(t) = value_at_end + slope_per_day * (t - fit_end_ts) / 86400

and a level is crossed at

    crossing_ts = fit_end_ts + (level - value_at_end) / slope_per_day * 86400

which reproduces the published dates exactly.

Confidence (D-10) follows the length of available history for the series
(`history_days`, first to last input point before the sharp-drop cut); the fit
window is published separately as `fit_start_ts`/`fit_end_ts`.

All thresholds are [ASSUMED] defaults from the research and are env-overridable
by the caller through `FitParams`. `statistics.linear_regression` and
`statistics.correlation` were verified locally on Python 3.11; `correlation`
raises StatisticsError on zero variance, so constant series are handled before
it is called. Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from statistics import correlation, linear_regression

_DAY = 86400.0


@dataclass(frozen=True)
class FitParams:
    bucket_hours: int = 6
    min_buckets: int = 8
    min_span_days: float = 2.0
    r2_min: float = 0.70
    r2_high: float = 0.90
    min_rise_30d: float = 1.0
    drop_min_abs: float = 5.0
    drop_range_fraction: float = 0.25
    confidence_medium_days: float = 14.0
    confidence_high_days: float = 60.0


@dataclass
class Fit:
    status: str  # "trending" | "stable" | "no_clear_trend"
    history_days: float
    slope_per_day: float | None = None
    value_at_end: float | None = None
    fit_start_ts: float | None = None
    fit_end_ts: float | None = None
    r2: float | None = None
    confidence: str | None = None
    last_value: float | None = None
    warn: float | None = None
    crit: float | None = None
    warn_ts: float | None = None
    crit_ts: float | None = None
    warn_date: str | None = None
    crit_date: str | None = None
    days_to_warn: float | None = None
    days_to_crit: float | None = None

    def to_payload(self, service: str, metric: str, unit: str) -> dict:
        payload = {f.name: getattr(self, f.name) for f in fields(self)}
        payload.update(service=service, metric=metric, unit=unit)
        return payload


def confidence_for(history_days: float, r2: float, params: FitParams) -> str:
    if history_days < params.confidence_medium_days:
        return "low"
    if history_days <= params.confidence_high_days or r2 < params.r2_high:
        return "medium"
    return "high"


def cut_after_last_sharp_drop(
    points: list[tuple[float, float]], params: FitParams
) -> list[tuple[float, float]]:
    """Return the points from the bucket after the last sharp drop.

    A sharp drop is a bucket-to-bucket fall larger than
    max(drop_min_abs, drop_range_fraction * (max - min)), so a 2-point wobble
    on a 90% disk is not a drop (D-11).
    """
    if len(points) < 2:
        return list(points)
    values = [v for _, v in points]
    threshold = max(
        params.drop_min_abs, params.drop_range_fraction * (max(values) - min(values))
    )
    start = 0
    for i in range(1, len(points)):
        if points[i - 1][1] - points[i][1] > threshold:
            start = i
    return list(points[start:])


def _iso_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _crossings(
    fit: Fit, warn: float | None, crit: float | None, now_ts: float
) -> None:
    if warn is not None and crit is not None and crit < warn:
        return  # inconsistent levels: no dates rather than misleading ones
    for level, ts_attr, date_attr, days_attr in (
        (warn, "warn_ts", "warn_date", "days_to_warn"),
        (crit, "crit_ts", "crit_date", "days_to_crit"),
    ):
        if level is None:
            continue
        if fit.last_value >= level:
            setattr(fit, days_attr, 0.0)  # already there, nothing ahead
            continue
        ts = fit.fit_end_ts + (level - fit.value_at_end) / fit.slope_per_day * _DAY
        setattr(fit, ts_attr, ts)
        setattr(fit, date_attr, _iso_date(ts))
        setattr(fit, days_attr, max(0.0, (ts - now_ts) / _DAY))


def fit_series(
    points: list[tuple[float, float]],
    warn: float | None,
    crit: float | None,
    params: FitParams,
    now_ts: float,
) -> Fit:
    pts = [(t, v) for t, v in points if math.isfinite(t) and math.isfinite(v)]
    history_days = (pts[-1][0] - pts[0][0]) / _DAY if len(pts) > 1 else 0.0
    result = Fit(
        status="no_clear_trend",
        history_days=history_days,
        last_value=pts[-1][1] if pts else None,
        warn=warn,
        crit=crit,
    )
    kept = cut_after_last_sharp_drop(pts, params)
    if (
        len(kept) < params.min_buckets
        or (kept[-1][0] - kept[0][0]) / _DAY < params.min_span_days
    ):
        return result
    values = [v for _, v in kept]
    if max(values) == min(values):
        result.status = "stable"
        return result

    t0 = kept[0][0]
    xs = [(t - t0) / _DAY for t, _ in kept]
    slope, _intercept = linear_regression(xs, values)
    r2 = correlation(xs, values) ** 2
    result.r2 = r2
    if r2 < params.r2_min:
        return result
    if slope * 30 < params.min_rise_30d:
        result.status = "stable"
        return result

    result.status = "trending"
    result.slope_per_day = slope
    result.fit_start_ts = kept[0][0]
    result.fit_end_ts = kept[-1][0]
    result.value_at_end = kept[-1][1]
    result.confidence = confidence_for(history_days, r2, params)
    _crossings(result, warn, crit, now_ts)
    return result
