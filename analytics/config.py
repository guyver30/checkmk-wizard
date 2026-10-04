"""Analytics container configuration, sourced entirely from environment variables.

D-06: every endpoint (broker, ClickHouse, MinIO) is an environment variable, so
the container is location-agnostic and moves to another machine by editing the
compose environment only.  D-05: nothing leaves the operator's tenancy -- there
is no third-party endpoint anywhere in this config.

Env names match `PollerConfig` (scripts/mqtt_poller.py) where a value is shared,
so the rollup code can move over unchanged.  Defaults for the metric sets and
fallback levels are seeded from the live catalog recorded in 14.2-01-SUMMARY.md.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

_logger = logging.getLogger("analytics.config")

# --- env-overridable defaults ------------------------------------------------

DEFAULT_MQTT_PORT = 1883
DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS = 5.0
DEFAULT_POLL_INTERVAL_SECONDS = 15
DEFAULT_ROLLUP_TZ = "Asia/Singapore"
DEFAULT_ROLLUP_BACKFILL_DAYS = 28
DEFAULT_ROLLUP_DELAY_MINUTES = 5
DEFAULT_AVAILABILITY_BUCKET = "fleet-availability"
# D-13: how often the evaluation loop runs.
DEFAULT_EVAL_INTERVAL_SECONDS = 900
# D-09: tier bands ("all bands are configurable").
DEFAULT_TIER_IMMEDIATE_DAYS = 3.0
DEFAULT_TIER_URGENT_DAYS = 20.0
DEFAULT_NEED_HORIZON_DAYS = 90.0
# D-10 / D-19a fit gate, seeded for the live data volume.
DEFAULT_FIT_R2_MIN = 0.70
DEFAULT_FIT_R2_HIGH = 0.90
DEFAULT_FIT_MIN_RISE_30D = 1.0
# D-16: configurable metric lists. Seeded from live catalog 14.2-01: filesystem
# used %, CPU utilization, memory used %.
DEFAULT_CHART_METRICS = ("fs_used_percent", "util", "mem_used_percent")
# D-16: CPU gets a fit and a chart but never a trend need, so it is left out.
# No lower-is-worse series was observed in the catalog, so none is excluded.
DEFAULT_TREND_NEED_METRICS = ("fs_used_percent", "mem_used_percent")

# --- fixed constants (not env; change in code if ever needed) ----------------

# D-10: confidence by how long the fitted series spans.
CONFIDENCE_MEDIUM_DAYS = 14.0
CONFIDENCE_HIGH_DAYS = 60.0
FIT_MIN_BUCKETS = 8
FIT_MIN_SPAN_DAYS = 2.0
FIT_BUCKET_HOURS = 6
FIT_LOOKBACK_DAYS = 90
DROP_MIN_ABS = 5.0
DROP_RANGE_FRACTION = 0.25
SUSTAINED_WINDOW_HOURS = 24
SUSTAINED_FRACTION = 0.8
RESOLVE_AFTER_CLEAN_CYCLES = 2

# D-10 low-confidence cap set (wear-type series). Seeded from live catalog
# 14.2-01, which showed no SMART/NVMe service, so this is empty. Add the exact
# names here once such a service is monitored.
WEAR_METRICS: frozenset[str] = frozenset()

# history.metrics has no unit column. Seeded from live catalog 14.2-01.
METRIC_UNITS: dict[str, str] = {
    "fs_used_percent": "%",
    "mem_used_percent": "%",
    "util": "%",
}

# D-12: analytics config supplies fallback (warn, crit) levels for series that
# the catalog showed without Checkmk levels. Only CPU `util` had warn/crit NULL
# (14.2-01); filesystem and memory carry their own levels.
FALLBACK_LEVELS: dict[str, tuple[float, float]] = {
    "util": (85.0, 95.0),
}

# Metric names are later quoted into SQL, so only this shape is accepted.
METRIC_NAME_RE = re.compile(r"^[A-Za-z0-9_.]{1,64}$")

# SMART/NVMe names are added via CHART_METRICS / TREND_NEED_METRICS env (and
# WEAR_METRICS in code) once such a service exists.
_WEAR_HINT_RE = re.compile(r"smart|nvme|realloc|wear", re.IGNORECASE)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid integer for %s=%r; using default %r", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning("Invalid float for %s=%r; using default %r", name, raw, default)
        return default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma list of metric names; names failing METRIC_NAME_RE are dropped."""
    raw = os.environ.get(name)
    if not raw:
        return default
    names: list[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if METRIC_NAME_RE.fullmatch(item):
            names.append(item)
        else:
            _logger.warning("Dropping invalid metric name %r from %s", item, name)
    return tuple(names)


@dataclass
class AnalyticsConfig:
    """Analytics runtime settings (D-06)."""

    mqtt_host: str = "mosquitto"
    mqtt_port: int = DEFAULT_MQTT_PORT
    mqtt_username: str = "analytics"
    mqtt_password: str = ""
    cmk_site_id: str = "dmc"
    log_level: str = "INFO"
    clickhouse_url: str = ""
    clickhouse_writer_user: str = "analytics_writer"
    clickhouse_writer_password: str = ""
    clickhouse_timeout_seconds: float = DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_addressing_style: str = "path"
    availability_bucket: str = DEFAULT_AVAILABILITY_BUCKET
    rollup_tz: str = DEFAULT_ROLLUP_TZ
    rollup_backfill_days: int = DEFAULT_ROLLUP_BACKFILL_DAYS
    rollup_delay_minutes: int = DEFAULT_ROLLUP_DELAY_MINUTES
    # Seconds of wall-clock time each history.host_state sample represents; the
    # poller writes one per poll, and the availability rollup scales counts by it.
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    eval_interval_seconds: int = DEFAULT_EVAL_INTERVAL_SECONDS
    tier_immediate_days: float = DEFAULT_TIER_IMMEDIATE_DAYS
    tier_urgent_days: float = DEFAULT_TIER_URGENT_DAYS
    need_horizon_days: float = DEFAULT_NEED_HORIZON_DAYS
    fit_r2_min: float = DEFAULT_FIT_R2_MIN
    fit_r2_high: float = DEFAULT_FIT_R2_HIGH
    fit_min_rise_30d: float = DEFAULT_FIT_MIN_RISE_30D
    chart_metrics: tuple[str, ...] = DEFAULT_CHART_METRICS
    trend_need_metrics: tuple[str, ...] = DEFAULT_TREND_NEED_METRICS

    def __repr__(self) -> str:
        # T-09-02: safe to log -- never render the MQTT password, the
        # ClickHouse writer password or the S3 keys. Defined explicitly so
        # @dataclass does not generate a repr that includes them.
        return (
            "AnalyticsConfig("
            f"mqtt_host={self.mqtt_host!r}, "
            f"mqtt_port={self.mqtt_port!r}, "
            f"mqtt_username={self.mqtt_username!r}, "
            "mqtt_password='***', "
            f"cmk_site_id={self.cmk_site_id!r}, "
            f"log_level={self.log_level!r}, "
            f"clickhouse_url={self.clickhouse_url!r}, "
            f"clickhouse_writer_user={self.clickhouse_writer_user!r}, "
            "clickhouse_writer_password='***', "
            f"clickhouse_timeout_seconds={self.clickhouse_timeout_seconds!r}, "
            f"s3_endpoint={self.s3_endpoint!r}, "
            "s3_access_key='***', "
            "s3_secret_key='***', "
            f"s3_region={self.s3_region!r}, "
            f"s3_addressing_style={self.s3_addressing_style!r}, "
            f"availability_bucket={self.availability_bucket!r}, "
            f"rollup_tz={self.rollup_tz!r}, "
            f"rollup_backfill_days={self.rollup_backfill_days!r}, "
            f"rollup_delay_minutes={self.rollup_delay_minutes!r}, "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, "
            f"eval_interval_seconds={self.eval_interval_seconds!r}, "
            f"tier_immediate_days={self.tier_immediate_days!r}, "
            f"tier_urgent_days={self.tier_urgent_days!r}, "
            f"need_horizon_days={self.need_horizon_days!r}, "
            f"fit_r2_min={self.fit_r2_min!r}, "
            f"fit_r2_high={self.fit_r2_high!r}, "
            f"fit_min_rise_30d={self.fit_min_rise_30d!r}, "
            f"chart_metrics={self.chart_metrics!r}, "
            f"trend_need_metrics={self.trend_need_metrics!r})"
        )

    @classmethod
    def from_env(cls) -> AnalyticsConfig:
        return cls(
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=_env_int("MQTT_PORT", DEFAULT_MQTT_PORT),
            mqtt_username=os.environ.get("MQTT_USERNAME", "analytics"),
            mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
            cmk_site_id=os.environ.get("CMK_SITE_ID", "dmc"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            clickhouse_url=os.environ.get("CLICKHOUSE_URL", "").rstrip("/"),
            clickhouse_writer_user=os.environ.get("CLICKHOUSE_WRITER_USER", "analytics_writer"),
            clickhouse_writer_password=os.environ.get("CLICKHOUSE_WRITER_PASSWORD", ""),
            clickhouse_timeout_seconds=_env_float(
                "CLICKHOUSE_TIMEOUT_SECONDS", DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS
            ),
            s3_endpoint=os.environ.get("S3_ENDPOINT", ""),
            s3_access_key=os.environ.get("S3_ACCESS_KEY", ""),
            s3_secret_key=os.environ.get("S3_SECRET_KEY", ""),
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_addressing_style=os.environ.get("S3_ADDRESSING_STYLE", "path"),
            availability_bucket=os.environ.get("AVAILABILITY_BUCKET", DEFAULT_AVAILABILITY_BUCKET),
            rollup_tz=os.environ.get("ROLLUP_TZ", DEFAULT_ROLLUP_TZ),
            rollup_backfill_days=_env_int("ROLLUP_BACKFILL_DAYS", DEFAULT_ROLLUP_BACKFILL_DAYS),
            rollup_delay_minutes=_env_int("ROLLUP_DELAY_MINUTES", DEFAULT_ROLLUP_DELAY_MINUTES),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
            eval_interval_seconds=_env_int("EVAL_INTERVAL_SECONDS", DEFAULT_EVAL_INTERVAL_SECONDS),
            tier_immediate_days=_env_float("TIER_IMMEDIATE_DAYS", DEFAULT_TIER_IMMEDIATE_DAYS),
            tier_urgent_days=_env_float("TIER_URGENT_DAYS", DEFAULT_TIER_URGENT_DAYS),
            need_horizon_days=_env_float("NEED_HORIZON_DAYS", DEFAULT_NEED_HORIZON_DAYS),
            fit_r2_min=_env_float("FIT_R2_MIN", DEFAULT_FIT_R2_MIN),
            fit_r2_high=_env_float("FIT_R2_HIGH", DEFAULT_FIT_R2_HIGH),
            fit_min_rise_30d=_env_float("FIT_MIN_RISE_30D", DEFAULT_FIT_MIN_RISE_30D),
            chart_metrics=_env_list("CHART_METRICS", DEFAULT_CHART_METRICS),
            trend_need_metrics=_env_list("TREND_NEED_METRICS", DEFAULT_TREND_NEED_METRICS),
        )


def smart_allowlist_warning(config: AnalyticsConfig) -> str | None:
    """Warning text when no chart metric is a wear-type (SMART/NVMe) name, else None.

    Live catalog 14.2-01 showed no such service, so disk-wear prediction is
    inactive until one is monitored and its names are added to the allow-lists.
    """
    if any(_WEAR_HINT_RE.search(m) or m in WEAR_METRICS for m in config.chart_metrics):
        return None
    return (
        "No SMART/NVMe wear metric is in CHART_METRICS: disk-wear prediction is inactive. "
        "Add the metric names to CHART_METRICS/TREND_NEED_METRICS once such a service is monitored."
    )
