import os

import pytest

from analytics import config as cfg
from analytics.config import AnalyticsConfig, smart_allowlist_warning

ENV_NAMES = {
    "MQTT_HOST", "MQTT_PORT", "MQTT_USERNAME", "MQTT_PASSWORD", "CMK_SITE_ID", "LOG_LEVEL",
    "CLICKHOUSE_URL", "CLICKHOUSE_WRITER_USER", "CLICKHOUSE_WRITER_PASSWORD",
    "CLICKHOUSE_TIMEOUT_SECONDS", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_REGION",
    "S3_ADDRESSING_STYLE", "AVAILABILITY_BUCKET", "ROLLUP_TZ", "ROLLUP_BACKFILL_DAYS",
    "ROLLUP_DELAY_MINUTES", "POLL_INTERVAL_SECONDS", "EVAL_INTERVAL_SECONDS", "TIER_IMMEDIATE_DAYS", "TIER_URGENT_DAYS",
    "NEED_HORIZON_DAYS", "FIT_R2_MIN", "FIT_R2_HIGH", "FIT_MIN_RISE_30D", "CHART_METRICS",
    "TREND_NEED_METRICS",
}


@pytest.fixture
def env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_with_empty_environment(env):
    c = AnalyticsConfig.from_env()
    assert c.eval_interval_seconds == 900
    assert (c.tier_immediate_days, c.tier_urgent_days, c.need_horizon_days) == (3.0, 20.0, 90.0)
    assert (c.fit_r2_min, c.fit_r2_high, c.fit_min_rise_30d) == (0.70, 0.90, 1.0)
    assert c.chart_metrics == ("fs_used_percent", "util", "mem_used_percent")
    assert c.trend_need_metrics == ("fs_used_percent", "mem_used_percent")
    assert c.clickhouse_url == ""
    assert c.mqtt_port == 1883


def test_list_parsing_and_invalid_names_dropped(env):
    env.setenv("CHART_METRICS", "a, b ,bad'name,,c.d")
    assert AnalyticsConfig.from_env().chart_metrics == ("a", "b", "c.d")


def test_malformed_numbers_fall_back(env, caplog):
    env.setenv("EVAL_INTERVAL_SECONDS", "soon")
    env.setenv("FIT_R2_MIN", "x")
    c = AnalyticsConfig.from_env()
    assert c.eval_interval_seconds == 900
    assert c.fit_r2_min == 0.70
    assert "EVAL_INTERVAL_SECONDS" in caplog.text


def test_only_documented_env_names_are_read(env):
    seen = set()

    class Recorder(dict):
        def get(self, key, default=None):
            seen.add(key)
            return default

    env.setattr(os, "environ", Recorder())
    AnalyticsConfig.from_env()
    assert seen == ENV_NAMES


def test_repr_masks_secrets(env):
    c = AnalyticsConfig(
        mqtt_password="mqttpw-123",
        clickhouse_writer_password="chpw-456",
        s3_access_key="akey-789",
        s3_secret_key="skey-000",
    )
    text = repr(c)
    assert "***" in text
    for secret in ("mqttpw-123", "chpw-456", "akey-789", "skey-000"):
        assert secret not in text


def test_smart_warning_when_no_wear_metric():
    assert smart_allowlist_warning(AnalyticsConfig()) is not None


def test_smart_warning_absent_when_wear_metric_present():
    c = AnalyticsConfig(chart_metrics=("fs_used_percent", "nvme_percentage_used"))
    assert smart_allowlist_warning(c) is None


def test_fixed_constants_not_env(env):
    assert cfg.CONFIDENCE_MEDIUM_DAYS == 14.0
    assert cfg.CONFIDENCE_HIGH_DAYS == 60.0
    assert cfg.WEAR_METRICS == frozenset()
    assert cfg.FALLBACK_LEVELS["util"][0] < cfg.FALLBACK_LEVELS["util"][1]
