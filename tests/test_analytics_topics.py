import importlib.util
import sys
from pathlib import Path

import pytest

from analytics import topics

_SPEC = importlib.util.spec_from_file_location(
    "mqtt_poller_for_topics",
    Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py",
)
poller = importlib.util.module_from_spec(_SPEC)
sys.modules["mqtt_poller_for_topics"] = poller
_SPEC.loader.exec_module(poller)


@pytest.fixture(autouse=True)
def _site_id():
    topics.set_site_id("testsite")
    poller.set_site_id("testsite")
    yield
    topics._site_prefix = None
    poller._site_prefix = None


@pytest.mark.parametrize(
    "bad", ["", "a/b", "a+b", "a#", "has space", "dmc\n", "1abc", "x" * 17]
)
def test_set_site_id_rejects_invalid(bad):
    with pytest.raises(ValueError, match="CMK_SITE_ID"):
        topics.set_site_id(bad)


def test_matches_poller_site_topic_and_relative():
    for suffix in ("lan/devices/topology", "admin/cmd", "x"):
        assert topics.site_topic(suffix) == poller.site_topic(suffix)
        full = topics.site_topic(suffix)
        assert topics.relative_topic(full) == poller.relative_topic(full) == suffix
    assert topics.relative_topic("other/x") == poller.relative_topic("other/x") is None


@pytest.mark.parametrize(
    "dev", ["linux1", "", "  ", "a/b", "a+b", "a#", "a\x00b", "a\x7fb", "ok-host.1"]
)
def test_is_publishable_matches_poller(dev):
    assert topics.is_publishable_device_id(dev) == poller.is_publishable_device_id(dev)


def test_site_topic_requires_site_id():
    topics._site_prefix = None
    with pytest.raises(RuntimeError):
        topics.site_topic("x")


def test_topic_builders():
    assert topics.need_status_topic("n-abc") == "sites/testsite/lan/needs/n-abc/status"
    assert topics.forecast_topic("linux1") == "sites/testsite/lan/forecasts/linux1"
    assert (
        topics.incident_narration_topic("incident-sw1")
        == "sites/testsite/lan/incidents/incident-sw1/narration"
    )
    assert topics.TRIAGE_CMD_TOPIC == "needs/triage/cmd"


def test_forecast_topic_rejects_unsafe_host():
    with pytest.raises(ValueError):
        topics.forecast_topic("a/b")


def test_need_id_re():
    assert topics.NEED_ID_RE.match("f-0123456789ab")
    assert not topics.NEED_ID_RE.match("x-0123456789ab")
    assert not topics.NEED_ID_RE.match("f-0123456789ab\n")
    assert not topics.NEED_ID_RE.match("f-0123456789a")
