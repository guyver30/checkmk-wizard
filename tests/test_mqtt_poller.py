import datetime
import importlib.util
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

# scripts/ is not an importable package (no precedent in this repo for
# importing a scripts/*.py module from tests/ — scripts/smoke_test_broker.py
# has no test file at all), so load it directly from its file path.
_SPEC = importlib.util.spec_from_file_location(
    "mqtt_poller", Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py"
)
poller = importlib.util.module_from_spec(_SPEC)
# Register in sys.modules before exec: @dataclass (with `from __future__
# import annotations` in mqtt_poller.py) looks up its own module via
# sys.modules[cls.__module__] while processing fields, which fails with
# a bare AttributeError if the module was never registered.
sys.modules["mqtt_poller"] = poller
_SPEC.loader.exec_module(poller)


@pytest.fixture(autouse=True)
def _site_id():
    poller.set_site_id("testsite")
    yield
    poller._site_prefix = None


# --- per-site topic prefix ----------------------------------------------------


def test_site_topic_prefixes_suffix_unchanged():
    assert poller.site_topic("lan/devices/topology") == "sites/testsite/lan/devices/topology"


@pytest.mark.parametrize(
    "bad", ["", "a/b", "a+b", "a#", "has space", "dmc\n", "1abc", "x" * 17]
)
def test_set_site_id_rejects_invalid(bad):
    with pytest.raises(ValueError, match="CMK_SITE_ID"):
        poller.set_site_id(bad)


@pytest.mark.parametrize("good", ["dmc", "a", "Site_01"])
def test_set_site_id_accepts_valid(good):
    poller.set_site_id(good)
    assert poller.site_topic("x") == f"sites/{good}/x"


def test_site_topic_before_set_site_id_raises():
    poller._site_prefix = None
    with pytest.raises(RuntimeError):
        poller.site_topic("lan/events/recent")


def test_relative_topic_strips_only_own_prefix():
    assert poller.relative_topic("sites/testsite/lan/events/recent") == "lan/events/recent"
    assert poller.relative_topic("lan/events/recent") is None
    assert poller.relative_topic("sites/other/lan/events/recent") is None


def test_topic_builders_are_prefixed():
    assert poller.device_status_topic("web1") == "sites/testsite/lan/devices/web1/status"
    assert poller.incident_status_topic("inc-x") == "sites/testsite/lan/incidents/inc-x/status"


def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    sock.recv.side_effect = [response, b""]
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock


# --- compute_overall_state --------------------------------------------------


def test_compute_overall_state_ok_warn_crit_unknown():
    assert poller.compute_overall_state(0, 0) == "OK"
    assert poller.compute_overall_state(0, 1) == "WARN"
    assert poller.compute_overall_state(0, 2) == "CRIT"
    assert poller.compute_overall_state(0, 3) == "UNKNOWN"


def test_compute_overall_state_host_down_or_unreachable_wins_outright():
    assert poller.compute_overall_state(1, 0) == "DOWN"
    assert poller.compute_overall_state(2, 0) == "DOWN"


def test_compute_overall_state_unmapped_service_state_degrades_to_unknown():
    assert poller.compute_overall_state(0, 99) == "UNKNOWN"


def test_compute_overall_state_down_and_unreachable_both_still_collapse_to_down():
    # Regression guard for Pitfall 6 (D-17): the new host_state_raw field
    # must not leak into compute_overall_state()'s existing collapse --
    # raw states 1 (DOWN) and 2 (UNREACHABLE) both still return "DOWN".
    assert poller.compute_overall_state(1, 0) == "DOWN"
    assert poller.compute_overall_state(2, 0) == "DOWN"


# --- host_state_label ---------------------------------------------------------


def test_host_state_label_maps_0_1_2_to_up_down_unreach():
    assert poller.host_state_label(0) == "UP"
    assert poller.host_state_label(1) == "DOWN"
    assert poller.host_state_label(2) == "UNREACH"
    assert poller.host_state_label(7) == "UP"


# --- is_publishable_device_id -----------------------------------------------


def test_is_publishable_device_id_rejects_topic_unsafe_and_empty_names():
    assert poller.is_publishable_device_id("lan/rogue") is False
    assert poller.is_publishable_device_id("host+1") is False
    assert poller.is_publishable_device_id("host#2") is False
    assert poller.is_publishable_device_id("") is False
    assert poller.is_publishable_device_id("   ") is False


def test_is_publishable_device_id_accepts_normal_hostnames():
    assert poller.is_publishable_device_id("web1") is True
    assert poller.is_publishable_device_id("switch-01.lan") is True


# --- topology_nodes -----------------------------------------------------------


def test_topology_nodes_emits_map_position_and_unmanaged():
    snapshot = poller.DeviceSnapshot(
        id="sw1",
        state="OK",
        in_downtime=False,
        acknowledged=False,
        device_type="NetworkDevice",
        folder="vlan10",
        map_position="120,-40",
        unmanaged=True,
    )
    nodes = poller.topology_nodes([snapshot])
    assert nodes == [
        {
            "id": "sw1",
            "parents": [],
            "device_type": "NetworkDevice",
            "folder": "vlan10",
            "alias": "",
            "map_position": "120,-40",
            "unmanaged": True,
            "criticality": "low",
            "service_criticality": {},
            "depends_on": [],
        }
    ]


def test_topology_nodes_include_criticality_service_criticality_and_depends_on():
    snapshot = poller.DeviceSnapshot(
        id="screen1",
        state="OK",
        in_downtime=False,
        acknowledged=False,
        device_type="Multimedia",
        folder="",
        criticality="critical",
        depends_on=["media-srv"],
        service_criticality={"cron": "high"},
    )
    nodes = poller.topology_nodes([snapshot])
    assert nodes[0]["criticality"] == "critical"
    assert nodes[0]["service_criticality"] == {"cron": "high"}
    assert nodes[0]["depends_on"] == ["media-srv"]


def test_topology_nodes_defaults_map_position_and_unmanaged_when_no_host_config_entry():
    snapshot = poller.DeviceSnapshot(
        id="web1", state="OK", in_downtime=False, acknowledged=False, device_type="server", folder=""
    )
    nodes = poller.topology_nodes([snapshot])
    assert nodes[0]["map_position"] is None
    assert nodes[0]["unmanaged"] is False


# --- topology_signature -------------------------------------------------------


def test_topology_signature_is_order_independent():
    nodes = [
        {"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10", "alias": ""},
        {"id": "b", "parents": [], "device_type": "switch", "folder": "vlan10", "alias": ""},
    ]
    shuffled = list(reversed(nodes))
    assert poller.topology_signature(nodes) == poller.topology_signature(shuffled)


def test_topology_signature_differs_on_parent_change():
    base = [{"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10", "alias": ""}]
    changed = [{"id": "a", "parents": ["c"], "device_type": "server", "folder": "vlan10", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_add_or_remove():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    added = base + [{"id": "b", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(added)
    assert poller.topology_signature(added) != poller.topology_signature([])


def test_topology_signature_differs_on_device_type_change():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    changed = [{"id": "a", "parents": [], "device_type": "switch", "folder": "", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_alias_change():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": "Old Name"}]
    changed = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": "New Name"}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_map_position_change():
    base = [
        {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "",
            "alias": "",
            "map_position": "0,0",
            "unmanaged": False,
        }
    ]
    changed = [{**base[0], "map_position": "120,-40"}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_unmanaged_change():
    base = [
        {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "",
            "alias": "",
            "map_position": None,
            "unmanaged": False,
        }
    ]
    changed = [{**base[0], "unmanaged": True}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_tolerates_nodes_missing_map_position_and_unmanaged_keys():
    # A hand-built node dict that predates Phase 13's two new keys must not
    # KeyError -- topology_signature() reads them with `.get()`, degrading
    # to the same None/False default `_normalise_restored_node()` backfills.
    legacy = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    current = [
        {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "",
            "alias": "",
            "map_position": None,
            "unmanaged": False,
        }
    ]
    assert poller.topology_signature(legacy) == poller.topology_signature(current)


# --- compute_incidents / incident_signature ----------------------------------


def test_compute_incidents_groups_down_host_and_unreachable_children():
    snapshots = [
        _snapshot("sw1", host_state_raw="DOWN"),
        _snapshot("a", host_state_raw="UNREACH", parents=["sw1"]),
        _snapshot("b", host_state_raw="UNREACH", parents=["sw1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["id"] == "incident-sw1"
    assert incident["root"] == "sw1"
    assert incident["root_state"] == "DOWN"
    assert incident["inferred"] is False
    assert incident["confirmed_down"] == []
    assert incident["not_observable"] == ["a", "b"]


def test_compute_incidents_multi_hop_unreachable_chain_joins_single_incident():
    snapshots = [
        _snapshot("core", host_state_raw="DOWN"),
        _snapshot("sw2", host_state_raw="UNREACH", parents=["core"]),
        _snapshot("lift1", host_state_raw="UNREACH", parents=["sw2"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["root"] == "core"
    assert incident["not_observable"] == ["lift1", "sw2"]
    assert incident["confirmed_down"] == []


def test_compute_incidents_nested_down_folds_into_upstream_incident():
    snapshots = [
        _snapshot("core", host_state_raw="DOWN"),
        _snapshot("sw3", host_state_raw="DOWN", parents=["core"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["root"] == "core"
    assert incident["confirmed_down"] == ["sw3"]
    assert incident["not_observable"] == []


def test_compute_incidents_three_level_down_chain_is_one_incident():
    # Regression for 14-REVIEW CR-01: nesting only looked one hop up, so `access` saw the
    # nested root `dist` but never the top root `core`, became a top root itself, and one
    # outage showed as two incident cards.
    snapshots = [
        _snapshot("core", host_state_raw="DOWN"),
        _snapshot("dist", host_state_raw="DOWN", parents=["core"]),
        _snapshot("access", host_state_raw="DOWN", parents=["dist"]),
        _snapshot("leaf", host_state_raw="UNREACH", parents=["access"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["root"] == "core"
    assert incident["confirmed_down"] == ["access", "dist"]
    assert incident["not_observable"] == ["leaf"]


def test_compute_incidents_down_parent_cycle_still_yields_one_incident():
    # A `parents` cycle of DOWN hosts has no natural top root; exactly one must be promoted.
    snapshots = [
        _snapshot("a", host_state_raw="DOWN", parents=["c"]),
        _snapshot("b", host_state_raw="DOWN", parents=["a"]),
        _snapshot("c", host_state_raw="DOWN", parents=["b"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1


def test_compute_incidents_unmanaged_switch_promoted_as_inferred_root_when_sibling_also_down():
    snapshots = [
        _snapshot("um1", state="OK", host_state_raw="UP", unmanaged=True),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
        _snapshot("gc2", host_state_raw="UNREACH", parents=["um1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["id"] == "incident-um1"
    assert incident["root"] == "um1"
    assert incident["root_state"] == "UP"
    assert incident["inferred"] is True
    assert incident["confirmed_down"] == []
    assert incident["not_observable"] == ["gc1", "gc2"]


def test_compute_incidents_lone_down_host_under_unmanaged_switch_is_its_own_incident():
    snapshots = [
        _snapshot("um1", state="OK", host_state_raw="UP", unmanaged=True),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
        _snapshot("gc3", host_state_raw="UP", parents=["um1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["id"] == "incident-gc1"
    assert incident["root"] == "gc1"
    assert incident["root_state"] == "DOWN"
    assert incident["inferred"] is False


def test_compute_incidents_non_ok_chain_must_be_contiguous():
    # DOWN host "h" sits under a healthy managed parent "p", which itself
    # sits under a DOWN grandparent "gp" -- the walk must stop at "p"
    # (UP, not traversable), so "h" and "gp" are two separate incidents.
    snapshots = [
        _snapshot("gp", host_state_raw="DOWN"),
        _snapshot("p", host_state_raw="UP", parents=["gp"]),
        _snapshot("h", host_state_raw="DOWN", parents=["p"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert {incident["root"] for incident in incidents} == {"gp", "h"}
    assert len(incidents) == 2
    for incident in incidents:
        assert incident["confirmed_down"] == []
        assert incident["not_observable"] == []


def test_compute_incidents_unreachable_host_with_no_down_ancestor_has_no_incident():
    snapshots = [
        _snapshot("p", host_state_raw="UP"),
        _snapshot("h", host_state_raw="UNREACH", parents=["p"]),
    ]
    assert poller.compute_incidents(snapshots) == []


def test_compute_incidents_all_hosts_up_returns_empty_list():
    snapshots = [_snapshot("a"), _snapshot("b", parents=["a"])]
    assert poller.compute_incidents(snapshots) == []


def test_compute_incidents_parent_cycle_terminates_and_assigns_single_incident():
    snapshots = [
        _snapshot("a", host_state_raw="DOWN", parents=["b"]),
        _snapshot("b", host_state_raw="DOWN", parents=["a"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    incident = incidents[0]
    members = {incident["root"], *incident["confirmed_down"]}
    assert members == {"a", "b"}


def _criticality_fixture(scr_state):
    return [
        _snapshot("core", host_state_raw="DOWN", criticality="low"),
        _snapshot("lift1", host_state_raw="UNREACH", parents=["core"], criticality="medium"),
        _snapshot("srv", host_state_raw="UP", depends_on=["lift1"]),
        _snapshot("scr", host_state_raw=scr_state, depends_on=["srv"], criticality="critical"),
    ]


def test_compute_incidents_worst_criticality_transitive_dependent_up_counts_one_tier_lower():
    incidents = poller.compute_incidents(_criticality_fixture(scr_state="UP"))
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["dependents"] == ["scr", "srv"]
    # scr is UP: critical (index 3) drops one tier to high (index 2). srv
    # defaults to "low" and is also UP, so it contributes index 0. The
    # root/consequence contribute low/medium. Overall worst is "high".
    assert incident["worst_criticality"] == "high"


def test_compute_incidents_worst_criticality_non_up_dependent_counts_full_tier():
    # scr is DOWN here, which makes it its own separate incident (it has no
    # parents linking it to "core") -- it is a dependent of core's incident
    # via depends_on, not a consequence of it, exactly per D-15's wording.
    incidents = poller.compute_incidents(_criticality_fixture(scr_state="DOWN"))
    assert len(incidents) == 2
    core_incident = next(incident for incident in incidents if incident["root"] == "core")
    assert core_incident["dependents"] == ["scr", "srv"]
    assert core_incident["worst_criticality"] == "critical"


def test_compute_incidents_worst_criticality_ignores_self_reference_and_unknown_depends_on():
    snapshots = [_snapshot("core", host_state_raw="DOWN", depends_on=["core", "ghost"])]
    incidents = poller.compute_incidents(snapshots)
    assert incidents[0]["dependents"] == []
    assert incidents[0]["worst_criticality"] == "low"


def test_compute_incidents_invalid_criticality_string_counts_as_low():
    snapshots = [_snapshot("core", host_state_raw="DOWN", criticality="urgent!!")]
    incidents = poller.compute_incidents(snapshots)
    assert incidents[0]["worst_criticality"] == "low"


def test_compute_incidents_since_uses_min_last_state_change_of_root_and_consequences():
    snapshots = [
        _snapshot("core", host_state_raw="DOWN", last_state_change=1790000100),
        _snapshot("lift1", host_state_raw="UNREACH", parents=["core"], last_state_change=1790000000),
    ]
    incidents = poller.compute_incidents(snapshots)
    expected = datetime.datetime.fromtimestamp(1790000000, datetime.UTC).isoformat()
    assert incidents[0]["since"] == expected


def test_compute_incidents_since_is_none_when_no_positive_last_state_change():
    incidents = poller.compute_incidents([_snapshot("core", host_state_raw="DOWN")])
    assert incidents[0]["since"] is None


def test_compute_incidents_since_excludes_inferred_root_own_last_state_change():
    # The root (um1) is inferred and its own host_state_raw is "UP", so its
    # last_state_change (1, deliberately the smallest value) must not feed
    # `since` -- only the DOWN/UNREACH consequences' timestamps may.
    snapshots = [
        _snapshot("um1", state="OK", host_state_raw="UP", unmanaged=True, last_state_change=1),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"], last_state_change=1790000000),
        _snapshot("gc2", host_state_raw="UNREACH", parents=["um1"], last_state_change=1790000500),
    ]
    incidents = poller.compute_incidents(snapshots)
    expected = datetime.datetime.fromtimestamp(1790000000, datetime.UTC).isoformat()
    assert incidents[0]["since"] == expected


def test_compute_incidents_output_sorted_by_id_with_exact_keys():
    snapshots = [
        _snapshot("z-switch", host_state_raw="DOWN"),
        _snapshot("a-switch", host_state_raw="DOWN"),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert [incident["id"] for incident in incidents] == ["incident-a-switch", "incident-z-switch"]
    for incident in incidents:
        assert set(incident.keys()) == {
            "id",
            "root",
            "root_state",
            "inferred",
            "confirmed_down",
            "not_observable",
            "dependents",
            "worst_criticality",
            "since",
        }


def test_incident_signature_reflects_dependents_and_worst_criticality():
    base = {
        "id": "incident-core",
        "root": "core",
        "root_state": "DOWN",
        "inferred": False,
        "confirmed_down": [],
        "not_observable": ["a"],
        "dependents": ["scr"],
        "worst_criticality": "high",
        "since": None,
    }
    changed = {**base, "worst_criticality": "critical"}
    assert poller.incident_signature(base) != poller.incident_signature(changed)
    assert poller.incident_signature(base) == poller.incident_signature({**base})


# --- extract_device_type --------------------------------------------------------


def test_extract_device_type_reads_bare_key():
    # Live-confirmed 2026-09-11 (plan 10-06, Checkmk 2.4.0p36.cre): Livestatus
    # keys a custom tag group by its bare group id, not the `tag_` prefix the
    # REST API uses for the same attribute.
    assert poller.extract_device_type({"device_type": "switch"}) == "switch"


def test_extract_device_type_resolves_livestatus_group_default():
    # Live-confirmed 2026-09-11 (plan 10-06): Livestatus resolves a tag
    # group's configured default for an untagged host (`other`) rather
    # than omitting the key, unlike the REST API's `extensions.attributes`.
    assert poller.extract_device_type({"device_type": "other"}) == "other"


def test_extract_device_type_defaults_to_unknown_when_key_absent():
    # `UNKNOWN_DEVICE_TYPE` is the exceptional case: the `device_type` tag
    # group doesn't exist on this site at all, not a normal untagged host.
    assert poller.extract_device_type({}) == "unknown"


# --- parse_perf_data ----------------------------------------------------------


def test_parse_perf_data_filesystem_shaped_string():
    raw = "/=45.2;80.00;90.00;0;488281.25 fs_size=488281.25;;;;"
    result = poller.parse_perf_data(raw)
    assert result["/"] == {"value": 45.2, "warn": 80.0, "crit": 90.0, "min": 0.0, "max": 488281.25}
    assert result["fs_size"] == {"value": 488281.25, "warn": None, "crit": None, "min": None, "max": None}


def test_parse_perf_data_cpu_shaped_string():
    result = poller.parse_perf_data("util=42.5;80;90;0;100")
    assert result == {"util": {"value": 42.5, "warn": 80.0, "crit": 90.0, "min": 0.0, "max": 100.0}}


def test_parse_perf_data_percent_suffixed_value():
    result = poller.parse_perf_data("mem_used_percent=23.0%;80;90;;")
    assert result["mem_used_percent"]["value"] == 23.0
    assert result["mem_used_percent"]["min"] is None
    assert result["mem_used_percent"]["max"] is None


def test_parse_perf_data_quoted_label_with_space():
    result = poller.parse_perf_data("'total used'=5;;;;")
    assert result["total used"]["value"] == 5.0


def test_parse_perf_data_garbage_token_skipped_sibling_still_parses():
    result = poller.parse_perf_data("notametric util=1;;;;")
    assert "util" in result
    assert "notametric" not in result


def test_parse_perf_data_empty_string_returns_empty_dict():
    assert poller.parse_perf_data("") == {}


def test_parse_perf_data_non_string_returns_empty_dict():
    assert poller.parse_perf_data(None) == {}


# --- PollerConfig.from_env ---------------------------------------------------


_ENV_VARS = (
    "LIVESTATUS_HOST",
    "LIVESTATUS_PORT",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "POLL_INTERVAL_SECONDS",
    "EVENTS_MAX_ENTRIES",
    "RECONCILE_TIMEOUT_SECONDS",
    "LOG_LEVEL",
    "CMK_REST_HOST",
    "CMK_REST_PORT",
    "CMK_SITE_ID",
    "CMK_REST_USERNAME",
    "CMK_REST_SECRET",
    "CLICKHOUSE_URL",
    "CLICKHOUSE_WRITER_USER",
    "CLICKHOUSE_WRITER_PASSWORD",
    "CLICKHOUSE_TIMEOUT_SECONDS",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_REGION",
    "S3_ADDRESSING_STYLE",
    "AVAILABILITY_BUCKET",
    "ROLLUP_TZ",
    "ROLLUP_BACKFILL_DAYS",
    "ROLLUP_DELAY_MINUTES",
)


def _clear_poller_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_poller_config_from_env_defaults_with_empty_environment(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.poll_interval_seconds == 15
    assert config.events_max_entries == 1000
    assert config.livestatus_port == 6557
    assert config.mqtt_port == 1883
    assert config.reconcile_timeout_seconds == 5.0


def test_poller_config_repr_never_contains_the_password_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("MQTT_USERNAME", "someuser")
    monkeypatch.setenv("MQTT_PASSWORD", "supersecret")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "***" in rendered
    assert "supersecret" not in rendered


def test_poller_config_from_env_reads_rest_credentials_with_defaults(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.cmk_rest_host == "checkmk"
    assert config.cmk_rest_port == 5000
    assert config.cmk_site_id == "dmc"
    assert config.cmk_rest_username == ""
    assert config.cmk_rest_secret == ""


def test_poller_config_repr_never_contains_the_rest_secret_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("CMK_REST_USERNAME", "automation")
    monkeypatch.setenv("CMK_REST_SECRET", "s3cr3t-value")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "s3cr3t-value" not in rendered
    assert "'***'" in rendered
    # Non-secret REST fields must still render in the clear.
    assert "cmk_rest_host='checkmk'" in rendered
    assert "cmk_rest_port=5000" in rendered
    assert "cmk_site_id='dmc'" in rendered
    assert "cmk_rest_username='automation'" in rendered


# --- cmk_rest_base_url / fetch_host_folders ---------------------------------


def _fake_urlopen(body: bytes, status_code: int = 200):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_cmk_rest_base_url_builds_expected_shape():
    config = _make_config(
        cmk_rest_host="checkmk", cmk_rest_port=5000, cmk_site_id="dmc"
    )
    assert poller.cmk_rest_base_url(config) == "http://checkmk:5000/dmc/check_mk/api/1.0"


def test_fetch_host_folders_parses_extensions_folder_from_collection():
    body = json.dumps(
        {
            "value": [
                {"id": "web1", "extensions": {"folder": "/vlan10"}},
                {"id": "web2", "extensions": {"folder": "/tower1/sub"}},
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"web1": "vlan10", "web2": "tower1/sub"}


def test_fetch_host_folders_missing_folder_field_maps_to_empty_string():
    body = json.dumps({"value": [{"id": "web1", "extensions": {}}]}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"web1": ""}


def test_fetch_host_folders_raises_rest_error_on_connection_failure():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        try:
            poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected RestError")


def test_fetch_host_folders_raises_rest_error_on_malformed_json():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"not-json{{{")):
        try:
            poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError:
            pass
        else:
            raise AssertionError("expected RestError, not a bare json.JSONDecodeError")


def test_fetch_host_folders_401_error_message_never_contains_username_or_secret():
    http_error = urllib.error.HTTPError(
        url="http://checkmk:5000/dmc/check_mk/api/1.0/domain-types/host_config/collections/all",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        try:
            poller.fetch_host_folders(
                "http://checkmk:5000/dmc/check_mk/api/1.0", "secretuser", "supersecretvalue", 10
            )
        except poller.RestError as exc:
            message = str(exc)
            assert "secretuser" not in message
            assert "supersecretvalue" not in message
        else:
            raise AssertionError("expected RestError")


# --- fetch_host_config -------------------------------------------------------


def test_fetch_host_config_parses_folder_map_position_and_unmanaged():
    body = json.dumps(
        {
            "value": [
                {
                    "id": "sw1",
                    "extensions": {
                        "folder": "/vlan10",
                        "attributes": {"labels": {"map_position": "120,-40", "unmanaged_switch": "yes"}},
                    },
                },
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"sw1": poller.HostConfigInfo(folder="vlan10", map_position="120,-40", unmanaged=True)}


def test_fetch_host_config_invalid_map_position_degrades_to_none():
    body = json.dumps(
        {
            "value": [
                {
                    "id": "web1",
                    "extensions": {
                        "folder": "/vlan10",
                        "attributes": {"labels": {"map_position": "not-a-position"}},
                    },
                },
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result["web1"].map_position is None


def test_fetch_host_config_unmanaged_requires_exact_yes_value():
    body = json.dumps(
        {
            "value": [
                {
                    "id": "web1",
                    "extensions": {"folder": "/", "attributes": {"labels": {"unmanaged_switch": "true"}}},
                },
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result["web1"].unmanaged is False


def test_fetch_host_config_missing_labels_defaults_to_none_and_false():
    body = json.dumps({"value": [{"id": "web1", "extensions": {"folder": "/vlan10"}}]}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"web1": poller.HostConfigInfo(folder="vlan10", map_position=None, unmanaged=False)}


def test_fetch_host_config_raises_rest_error_on_connection_failure():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        try:
            poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected RestError")


def test_fetch_host_config_raises_rest_error_on_malformed_json():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"not-json{{{")):
        try:
            poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError:
            pass
        else:
            raise AssertionError("expected RestError, not a bare json.JSONDecodeError")


# --- fetch_host_config: Phase 14 criticality/service_criticality/depends_on labels ---


def test_fetch_host_config_parses_criticality_labels():
    body = json.dumps(
        {
            "value": [
                {
                    "id": "screen1",
                    "extensions": {
                        "folder": "/vlan10",
                        "attributes": {
                            "labels": {
                                "criticality": "high",
                                "service_criticality": "cron=high;ModemManager=low",
                                "depends_on": "media-srv,core.sw1, bad host ,media-srv",
                            }
                        },
                    },
                },
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    info = result["screen1"]
    assert info.criticality == "high"
    assert info.service_criticality == {"cron": "high", "ModemManager": "low"}
    assert info.depends_on == ["media-srv", "core.sw1"]


def test_fetch_host_config_invalid_criticality_degrades_to_low():
    for raw in ("HIGH", "urgent", 5):
        body = json.dumps(
            {"value": [{"id": "web1", "extensions": {"folder": "/", "attributes": {"labels": {"criticality": raw}}}}]}
        ).encode()
        with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
            result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        assert result["web1"].criticality == "low"


def test_parse_service_criticality_skips_malformed_entries():
    raw = "cron=high;=low;noequals;bad:name=high;also bad tier=nope; =medium; cron2 = medium "
    result = poller._parse_service_criticality(raw)
    assert result == {"cron": "high", "cron2": "medium"}
    assert poller._parse_service_criticality(123) == {}
    assert poller._parse_service_criticality(None) == {}


def test_parse_service_criticality_caps_entries():
    raw = ";".join(f"svc{i}=low" for i in range(250))
    result = poller._parse_service_criticality(raw)
    assert len(result) == poller._MAX_SERVICE_CRITICALITY_ENTRIES
    assert "svc0" in result
    assert "svc199" in result
    assert "svc200" not in result


def test_parse_depends_on_drops_invalid_self_and_duplicate_ids():
    raw = "media-srv,core.sw1, bad host ,media-srv,screen1"
    assert poller._parse_depends_on(raw, "screen1") == ["media-srv", "core.sw1"]
    assert poller._parse_depends_on(None, "screen1") == []
    assert poller._parse_depends_on(123, "screen1") == []


def test_parse_depends_on_caps_entries():
    raw = ",".join(f"host{i}" for i in range(75))
    result = poller._parse_depends_on(raw, "screen1")
    assert len(result) == poller._MAX_DEPENDS_ON_ENTRIES
    assert result[0] == "host0"
    assert result[-1] == f"host{poller._MAX_DEPENDS_ON_ENTRIES - 1}"


def test_fetch_host_config_missing_phase14_labels_defaults():
    body = json.dumps({"value": [{"id": "web1", "extensions": {"folder": "/vlan10"}}]}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_config("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    info = result["web1"]
    assert info.criticality == "low"
    assert info.service_criticality == {}
    assert info.depends_on == []


def test_fetch_host_folders_derives_from_fetch_host_config():
    """fetch_host_folders() is now a thin wrapper -- one REST call backs both."""
    body = json.dumps(
        {
            "value": [
                {
                    "id": "sw1",
                    "extensions": {
                        "folder": "/vlan10",
                        "attributes": {"labels": {"map_position": "0,0"}},
                    },
                },
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)) as mock_urlopen:
        result = poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"sw1": "vlan10"}
    assert mock_urlopen.call_count == 1


# --- ClickHouse config fields ------------------------------------------------


def test_poller_config_from_env_clickhouse_defaults_with_empty_environment(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.clickhouse_url == ""
    assert config.clickhouse_writer_user == "poller_writer"
    assert config.clickhouse_writer_password == ""
    assert config.clickhouse_timeout_seconds == 5.0


def test_poller_config_from_env_clickhouse_url_trailing_slash_stripped(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("CLICKHOUSE_URL", "http://clickhouse:8123/")
    config = poller.PollerConfig.from_env()
    assert config.clickhouse_url == "http://clickhouse:8123"


def test_poller_config_from_env_clickhouse_timeout_falls_back_on_bad_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("CLICKHOUSE_TIMEOUT_SECONDS", "abc")
    config = poller.PollerConfig.from_env()
    assert config.clickhouse_timeout_seconds == 5.0


def test_poller_config_repr_never_contains_the_clickhouse_password_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("CLICKHOUSE_URL", "http://clickhouse:8123")
    monkeypatch.setenv("CLICKHOUSE_WRITER_PASSWORD", "ch-s3cr3t")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "ch-s3cr3t" not in rendered
    assert "clickhouse_writer_password='***'" in rendered
    assert "clickhouse_url='http://clickhouse:8123'" in rendered


# --- ClickHouse HTTP choke point ---------------------------------------------


def test_clickhouse_insert_posts_jsoneachrow_body():
    rows = [{"ts": "2026-09-28 01:02:03", "host": "web1", "service": "CPU", "metric": "util", "value": 1.0, "warn": None, "crit": None}]
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"")) as mock_urlopen:
        poller._clickhouse_insert(
            "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", rows, 5.0
        )
    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    decoded_query = urllib.parse.unquote(request.full_url.split("?query=", 1)[1])
    assert decoded_query == "INSERT INTO history.metrics FORMAT JSONEachRow"
    assert request.get_method() == "POST"
    assert request.data == json.dumps(rows[0], allow_nan=False).encode("utf-8")
    assert request.get_header("X-clickhouse-user") == "poller_writer"
    assert request.get_header("X-clickhouse-key") == "s3cr3t"
    assert "s3cr3t" not in request.full_url


def test_clickhouse_insert_joins_multiple_rows_with_newlines():
    rows = [
        {"ts": "2026-09-28 01:02:03", "host": "web1", "folder": "vlan10", "state": 0, "in_downtime": 0},
        {"ts": "2026-09-28 01:02:03", "host": "web2", "folder": "vlan10", "state": 1, "in_downtime": 0},
    ]
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"")) as mock_urlopen:
        poller._clickhouse_insert(
            "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.host_state", rows, 5.0
        )
    request = mock_urlopen.call_args[0][0]
    expected = "\n".join(json.dumps(row, allow_nan=False) for row in rows).encode("utf-8")
    assert request.data == expected


def test_clickhouse_insert_empty_rows_makes_no_request():
    with patch("urllib.request.urlopen") as mock_urlopen:
        poller._clickhouse_insert(
            "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [], 5.0
        )
    mock_urlopen.assert_not_called()


def test_clickhouse_insert_unlisted_table_raises_without_a_request():
    with patch("urllib.request.urlopen") as mock_urlopen:
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123",
                "poller_writer",
                "s3cr3t",
                "system.query_log",
                [{"a": 1}],
                5.0,
            )
        except poller.ClickHouseError:
            pass
        else:
            raise AssertionError("expected ClickHouseError")
    mock_urlopen.assert_not_called()


def test_clickhouse_insert_nan_value_raises_without_a_request():
    with patch("urllib.request.urlopen") as mock_urlopen:
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123",
                "poller_writer",
                "s3cr3t",
                "history.metrics",
                [{"value": float("nan")}],
                5.0,
            )
        except poller.ClickHouseError:
            pass
        else:
            raise AssertionError("expected ClickHouseError")
    mock_urlopen.assert_not_called()


def test_clickhouse_insert_connection_failure_becomes_clickhouse_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [{"a": 1}], 5.0
            )
        except poller.ClickHouseError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected ClickHouseError")


def test_clickhouse_insert_url_error_becomes_clickhouse_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [{"a": 1}], 5.0
            )
        except poller.ClickHouseError:
            pass
        else:
            raise AssertionError("expected ClickHouseError")


def test_clickhouse_insert_timeout_becomes_clickhouse_error():
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [{"a": 1}], 5.0
            )
        except poller.ClickHouseError:
            pass
        else:
            raise AssertionError("expected ClickHouseError")


def test_clickhouse_insert_http_error_message_includes_response_body():
    http_error = urllib.error.HTTPError(
        url="http://clickhouse:8123/?query=x",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=MagicMock(read=MagicMock(return_value=b"Table history.metrics doesn't exist")),
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [{"a": 1}], 5.0
            )
        except poller.ClickHouseError as exc:
            assert "Table history.metrics doesn't exist" in str(exc)
        else:
            raise AssertionError("expected ClickHouseError")


def test_clickhouse_insert_http_error_with_no_body_does_not_raise_a_different_exception():
    http_error = urllib.error.HTTPError(
        url="http://clickhouse:8123/?query=x", code=403, msg="Forbidden", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        try:
            poller._clickhouse_insert(
                "http://clickhouse:8123", "poller_writer", "s3cr3t", "history.metrics", [{"a": 1}], 5.0
            )
        except poller.ClickHouseError:
            pass
        else:
            raise AssertionError("expected ClickHouseError")


def test_clickhouse_query_parses_jsoneachrow_response_and_uses_get():
    body = b'{"host":"web1","state":0}\n{"host":"web2","state":1}\n'
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)) as mock_urlopen:
        result = poller._clickhouse_query(
            "http://clickhouse:8123", "reader", "s3cr3t", "SELECT host, state FROM history.host_state", 5.0
        )
    assert result == [{"host": "web1", "state": 0}, {"host": "web2", "state": 1}]
    request = mock_urlopen.call_args[0][0]
    assert request.get_method() == "GET"
    decoded_query = urllib.parse.unquote(request.full_url.split("?query=", 1)[1])
    assert decoded_query == "SELECT host, state FROM history.host_state FORMAT JSONEachRow"


def test_clickhouse_query_empty_body_returns_empty_list():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"")):
        result = poller._clickhouse_query(
            "http://clickhouse:8123", "reader", "s3cr3t", "SELECT 1", 5.0
        )
    assert result == []


def test_clickhouse_command_posts_sql_as_body_and_returns_decoded_text():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"Ok.\n")) as mock_urlopen:
        result = poller._clickhouse_command(
            "http://clickhouse:8123", "poller_writer", "s3cr3t", "INSERT INTO FUNCTION s3(...) SELECT 1", 5.0
        )
    assert result == "Ok.\n"
    request = mock_urlopen.call_args[0][0]
    assert request.get_method() == "POST"
    assert request.data == b"INSERT INTO FUNCTION s3(...) SELECT 1"


# --- build_history_rows / write_history --------------------------------------
#
# Reuses the `_service()` helper (defined below, under "classify_host_services
# / services_signature") and the `_snapshot()` helper (defined further below,
# under "run_cycle") -- both are plain module-level functions, resolved at
# call time, so their definition order relative to these tests does not
# matter.


_TS = datetime.datetime(2026, 9, 28, 1, 2, 3, tzinfo=datetime.UTC)


def test_build_history_rows_stamps_every_row_with_the_same_utc_timestamp():
    batch = poller.build_history_rows(
        [_snapshot("web1", folder="vlan10")],
        [_service("web1", "CPU utilization", "OK", perf_data={"util": {"value": 1.0}})],
        _TS,
    )
    assert batch.host_state[0]["ts"] == "2026-09-28 01:02:03"
    assert batch.service_state[0]["ts"] == "2026-09-28 01:02:03"
    assert batch.metrics[0]["ts"] == "2026-09-28 01:02:03"


def test_build_history_rows_converts_non_utc_ts_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=8))  # Asia/Singapore offset
    local_ts = datetime.datetime(2026, 9, 28, 9, 2, 3, tzinfo=tz)  # == 01:02:03 UTC
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], None, local_ts)
    assert batch.host_state[0]["ts"] == "2026-09-28 01:02:03"


def test_build_history_rows_host_state_code_mapping_and_in_downtime():
    up, down, unreach, weird = (
        _snapshot("web1", folder="vlan10", host_state_raw="UP"),
        _snapshot("web2", folder="vlan10", host_state_raw="DOWN", in_downtime=True),
        _snapshot("web3", folder="vlan10", host_state_raw="UNREACH"),
        _snapshot("web4", folder="vlan10", host_state_raw="bogus"),
    )
    batch = poller.build_history_rows([up, down, unreach, weird], None, _TS)
    rows_by_host = {row["host"]: row for row in batch.host_state}
    assert rows_by_host["web1"] == {
        "ts": "2026-09-28 01:02:03", "host": "web1", "folder": "vlan10", "state": 0, "in_downtime": 0
    }
    assert rows_by_host["web2"]["state"] == 1
    assert rows_by_host["web2"]["in_downtime"] == 1
    assert rows_by_host["web3"]["state"] == 2
    assert rows_by_host["web4"]["state"] == 0


def test_build_history_rows_service_state_raw_out_of_range_becomes_unknown():
    service = _service("web1", "CPU utilization", "OK")
    service.state_raw = 99
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], [service], _TS)
    assert batch.service_state == [
        {"ts": "2026-09-28 01:02:03", "host": "web1", "service": "CPU utilization", "state": 3}
    ]


def test_build_history_rows_metric_rows_carry_value_warn_crit():
    service = _service(
        "web1", "CPU utilization", "OK", perf_data={"util": {"value": 42.5, "warn": 80.0, "crit": 90.0}}
    )
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], [service], _TS)
    assert batch.metrics == [
        {
            "ts": "2026-09-28 01:02:03",
            "host": "web1",
            "service": "CPU utilization",
            "metric": "util",
            "value": 42.5,
            "warn": 80.0,
            "crit": 90.0,
        }
    ]


def test_build_history_rows_skips_non_finite_metric_value_and_nulls_non_finite_thresholds():
    service = _service(
        "web1",
        "CPU utilization",
        "OK",
        perf_data={
            "bad_nan": {"value": float("nan")},
            "bad_inf": {"value": float("inf")},
            "bad_type": {"value": "not-a-number"},
            "good": {"value": 1.0, "warn": float("nan"), "crit": float("inf")},
        },
    )
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], [service], _TS)
    assert [row["metric"] for row in batch.metrics] == ["good"]
    assert batch.metrics[0]["warn"] is None
    assert batch.metrics[0]["crit"] is None


def test_build_history_rows_no_row_has_a_key_outside_the_contract_columns():
    service = _service(
        "web1", "CPU utilization", "OK", plugin_output="should never appear", perf_data={"util": {"value": 1.0}}
    )
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], [service], _TS)
    assert set(batch.host_state[0]) == {"ts", "host", "folder", "state", "in_downtime"}
    assert set(batch.service_state[0]) == {"ts", "host", "service", "state"}
    assert set(batch.metrics[0]) == {"ts", "host", "service", "metric", "value", "warn", "crit"}


def test_build_history_rows_services_none_yields_empty_service_and_metric_lists():
    batch = poller.build_history_rows([_snapshot("web1", folder="vlan10")], None, _TS)
    assert batch.service_state == []
    assert batch.metrics == []
    assert len(batch.host_state) == 1


def test_write_history_no_op_when_clickhouse_url_unset():
    config = _make_config(clickhouse_url="")
    batch = poller.HistoryBatch(metrics=[{"a": 1}], host_state=[{"a": 1}], service_state=[{"a": 1}])
    with patch.object(poller, "_clickhouse_insert") as mock_insert:
        poller.write_history(config, batch)
    mock_insert.assert_not_called()


def test_write_history_inserts_all_three_tables_separately():
    config = _make_config(clickhouse_url="http://clickhouse:8123")
    batch = poller.HistoryBatch(
        metrics=[{"m": 1}], host_state=[{"h": 1}], service_state=[{"s": 1}]
    )
    with patch.object(poller, "_clickhouse_insert") as mock_insert:
        poller.write_history(config, batch)
    tables_called = [call.args[3] for call in mock_insert.call_args_list]
    assert tables_called == ["history.metrics", "history.host_state", "history.service_state"]


def test_write_history_metrics_failure_still_attempts_host_and_service_state_and_logs_warning(caplog):
    config = _make_config(clickhouse_url="http://clickhouse:8123")
    batch = poller.HistoryBatch(
        metrics=[{"m": 1}], host_state=[{"h": 1}], service_state=[{"s": 1}]
    )
    with (
        caplog.at_level("WARNING", logger=poller._logger.name),
        patch.object(
            poller,
            "_clickhouse_insert",
            side_effect=[poller.ClickHouseError("boom"), None, None],
        ) as mock_insert,
    ):
        poller.write_history(config, batch)
    assert mock_insert.call_count == 3
    assert any("no data" in record.getMessage() for record in caplog.records)


# --- Availability rollups: day math and figures (Phase 14.1, D-45..D-53) ----


def test_local_day_bounds_singapore_midnight_to_midnight_utc():
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    start, end = poller.local_day_bounds(datetime.date(2026, 9, 27), tz)
    assert start == datetime.datetime(2026, 9, 26, 16, 0, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 9, 27, 16, 0, tzinfo=datetime.UTC)
    assert start.tzinfo is not None and end.tzinfo is not None


def test_rollup_days_to_check_ascending_within_backfill_window():
    days = poller.rollup_days_to_check(
        today_local=datetime.date(2026, 9, 28),
        first_data_day=datetime.date(2026, 9, 20),
        backfill_days=28,
    )
    assert days == [datetime.date(2026, 9, 20) + datetime.timedelta(days=i) for i in range(8)]


def test_rollup_days_to_check_no_first_data_day_returns_empty():
    assert poller.rollup_days_to_check(datetime.date(2026, 9, 28), None, 28) == []


def test_rollup_days_to_check_first_data_day_today_returns_empty():
    today = datetime.date(2026, 9, 28)
    assert poller.rollup_days_to_check(today, today, 28) == []


def test_rollup_days_to_check_first_data_day_far_in_past_clamps_to_backfill_window():
    today = datetime.date(2026, 9, 28)
    first = today - datetime.timedelta(days=60)
    days = poller.rollup_days_to_check(today, first, 28)
    assert len(days) == 28
    assert days[0] == today - datetime.timedelta(days=28)
    assert days[-1] == today - datetime.timedelta(days=1)


def test_rollup_object_keys_hive_style_parquet_prefix():
    json_key, parquet_key = poller.rollup_object_keys(datetime.date(2026, 9, 7))
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
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=5760)], 15
    )
    device = _device_row(rows)
    assert device["up_minutes"] == 1440
    assert device["up_pct"] == 100
    assert device["availability_pct"] == 100
    assert device["no_data_minutes"] == 0


def test_compute_daily_availability_half_up_half_down():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, down_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 50
    assert device["up_pct"] == 50
    assert device["down_pct"] == 50


def test_compute_daily_availability_unreachable_excluded_from_availability():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, unreach_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 100
    assert device["unobserved_pct"] == 50


def test_compute_daily_availability_downtime_excluded_from_availability():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880, downtime_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["availability_pct"] == 100
    assert device["downtime_minutes"] == 720
    assert device["downtime_pct"] == 50


def test_compute_daily_availability_partial_samples_report_no_data():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples=2880)], 15
    )
    device = _device_row(rows)
    assert device["no_data_minutes"] == 720
    assert device["no_data_pct"] == 50
    assert device["availability_pct"] == 100


def test_compute_daily_availability_zero_samples_is_all_no_data():
    rows = poller.compute_daily_availability(datetime.date(2026, 9, 27), [_host_row()], 15)
    device = _device_row(rows)
    assert device["no_data_pct"] == 100
    assert device["availability_pct"] is None


def test_compute_daily_availability_more_samples_than_a_day_holds():
    rows = poller.compute_daily_availability(
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
    rows = poller.compute_daily_availability(
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
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", folder="", up_samples=5760)], 15
    )
    folder_row = next(r for r in rows if r["group_type"] == "folder")
    assert folder_row["entity_key"] == poller.FOLDERLESS_GROUP_KEY


def test_compute_daily_availability_fleet_row_always_present_and_last():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", up_samples=5760)], 15
    )
    assert rows[-1]["group_type"] == "fleet"
    assert rows[-1]["entity_key"] == poller.FLEET_GROUP_KEY


def test_compute_daily_availability_empty_host_list_yields_only_fleet_row():
    rows = poller.compute_daily_availability(datetime.date(2026, 9, 27), [], 15)
    assert len(rows) == 1
    fleet = rows[0]
    assert fleet["group_type"] == "fleet"
    assert fleet["device_count"] == 0
    assert fleet["no_data_pct"] == 100
    assert fleet["availability_pct"] is None


def test_compute_daily_availability_string_sample_counts_accepted():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(up_samples="5760")], 15
    )
    assert _device_row(rows)["up_minutes"] == 1440


def test_compute_daily_availability_devices_before_folders_before_fleet():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27),
        [_host_row(host="a", folder="/x", up_samples=5760)],
        15,
    )
    kinds = [(r["entity_type"], r["group_type"]) for r in rows]
    assert kinds == [("device", ""), ("group", "folder"), ("group", "fleet")]


def test_availability_document_shape_matches_schema():
    rows = poller.compute_daily_availability(
        datetime.date(2026, 9, 27), [_host_row(host="a", folder="/x", up_samples=5760)], 15
    )
    doc = poller.availability_document(
        datetime.date(2026, 9, 27),
        rows,
        timezone_name="Asia/Singapore",
        poll_interval_seconds=15,
        generated_at_iso="2026-09-28T00:05:00+00:00",
    )
    assert doc["schema_version"] == poller.AVAILABILITY_SCHEMA_VERSION
    assert doc["date"] == "2026-09-27"
    assert doc["timezone"] == "Asia/Singapore"
    assert doc["poll_interval_seconds"] == 15
    assert doc["generated_at"] == "2026-09-28T00:05:00+00:00"
    assert len(doc["devices"]) == 1
    assert doc["devices"][0]["host"] == "a"
    assert len(doc["groups"]) == 2
    assert poller.availability_document_problems(doc) == []


def test_availability_document_problems_detects_wrong_schema_version():
    doc = {"schema_version": 99, "date": "2026-09-27", "devices": [], "groups": []}
    assert poller.availability_document_problems(doc) != []


def test_availability_document_problems_detects_bad_date():
    doc = {"schema_version": poller.AVAILABILITY_SCHEMA_VERSION, "date": "not-a-date",
           "devices": [], "groups": []}
    assert poller.availability_document_problems(doc) != []


def test_availability_document_problems_detects_pct_out_of_range():
    doc = {
        "schema_version": poller.AVAILABILITY_SCHEMA_VERSION,
        "date": "2026-09-27",
        "devices": [{"up_pct": 150, "down_pct": 0, "unobserved_pct": 0, "downtime_pct": 0,
                     "no_data_pct": 0, "availability_pct": None}],
        "groups": [],
    }
    assert poller.availability_document_problems(doc) != []


def test_availability_document_problems_detects_non_numeric_figure():
    doc = {
        "schema_version": poller.AVAILABILITY_SCHEMA_VERSION,
        "date": "2026-09-27",
        "devices": [{"up_pct": "100", "down_pct": 0, "unobserved_pct": 0, "downtime_pct": 0,
                     "no_data_pct": 0, "availability_pct": None}],
        "groups": [],
    }
    assert poller.availability_document_problems(doc) != []


# --- Availability rollups: S3 writer, ClickHouse fetch, JSON+Parquet (Phase 14.1) ---


def test_poller_config_from_env_s3_defaults_with_empty_environment(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.s3_endpoint == ""
    assert config.s3_access_key == ""
    assert config.s3_secret_key == ""
    assert config.s3_region == "us-east-1"
    assert config.s3_addressing_style == "path"
    assert config.availability_bucket == poller.DEFAULT_AVAILABILITY_BUCKET
    assert config.rollup_tz == poller.DEFAULT_ROLLUP_TZ
    assert config.rollup_backfill_days == poller.DEFAULT_ROLLUP_BACKFILL_DAYS
    assert config.rollup_delay_minutes == poller.DEFAULT_ROLLUP_DELAY_MINUTES


def test_poller_config_from_env_s3_reads_configured_values(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "s3cr3t")
    monkeypatch.setenv("S3_REGION", "us-west-2")
    monkeypatch.setenv("S3_ADDRESSING_STYLE", "virtual")
    monkeypatch.setenv("AVAILABILITY_BUCKET", "custom-bucket")
    monkeypatch.setenv("ROLLUP_TZ", "UTC")
    monkeypatch.setenv("ROLLUP_BACKFILL_DAYS", "10")
    monkeypatch.setenv("ROLLUP_DELAY_MINUTES", "7")
    config = poller.PollerConfig.from_env()
    assert config.s3_endpoint == "http://minio:9000"
    assert config.s3_access_key == "minioadmin"
    assert config.s3_secret_key == "s3cr3t"
    assert config.s3_region == "us-west-2"
    assert config.s3_addressing_style == "virtual"
    assert config.availability_bucket == "custom-bucket"
    assert config.rollup_tz == "UTC"
    assert config.rollup_backfill_days == 10
    assert config.rollup_delay_minutes == 7


def test_poller_config_repr_never_contains_s3_secret_or_access_key_values(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("S3_ACCESS_KEY", "AKIASECRETVALUE")
    monkeypatch.setenv("S3_SECRET_KEY", "verysecrets3value")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "AKIASECRETVALUE" not in rendered
    assert "verysecrets3value" not in rendered
    assert "s3_access_key='***'" in rendered
    assert "s3_secret_key='***'" in rendered


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
    result = poller.write_if_absent(s3, "bucket", "key.json", b"hello", "application/json")
    assert result is True
    assert s3.objects[("bucket", "key.json")] == b"hello"


def test_write_if_absent_second_call_returns_false_and_leaves_bytes_unchanged():
    s3 = _FakeS3()
    poller.write_if_absent(s3, "bucket", "key.json", b"hello", "application/json")
    result = poller.write_if_absent(s3, "bucket", "key.json", b"changed", "application/json")
    assert result is False
    assert s3.objects[("bucket", "key.json")] == b"hello"


def test_write_if_absent_head_error_other_than_404_reraises():
    class _BrokenS3(_FakeS3):
        def head_object(self, Bucket, Key):
            raise _client_error("403")

    with pytest.raises(botocore.exceptions.ClientError):
        poller.write_if_absent(_BrokenS3(), "bucket", "key.json", b"hello", "application/json")


def _rollup_config(**overrides) -> "poller.PollerConfig":
    defaults = {
        "clickhouse_url": "http://clickhouse:8123",
        "clickhouse_writer_user": "poller_writer",
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
    json_key, parquet_key = poller.rollup_object_keys(day)
    s3.objects[("fleet-availability", json_key)] = b"{}"
    s3.objects[("fleet-availability", parquet_key)] = b"parquet"
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "_clickhouse_query") as mock_query,
        patch.object(poller, "_clickhouse_insert") as mock_insert,
        patch.object(poller, "_clickhouse_command") as mock_command,
    ):
        result = poller.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "skipped"
    mock_query.assert_not_called()
    mock_insert.assert_not_called()
    mock_command.assert_not_called()


def test_rollup_one_day_writes_json_and_parquet_when_neither_exists():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    start_utc, end_utc = poller.local_day_bounds(day, tz)
    host_row = {
        "host": "a",
        "folder": "",
        "up_samples": "5760",
        "down_samples": "0",
        "unreach_samples": "0",
        "downtime_samples": "0",
    }
    with (
        patch.object(poller, "_clickhouse_query", return_value=[host_row]) as mock_query,
        patch.object(poller, "_clickhouse_insert") as mock_insert,
        patch.object(poller, "_clickhouse_command") as mock_command,
    ):
        result = poller.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    called_sql = mock_query.call_args.args[3]
    assert start_utc.strftime("%Y-%m-%d %H:%M:%S") in called_sql
    assert end_utc.strftime("%Y-%m-%d %H:%M:%S") in called_sql
    assert mock_insert.call_args.args[3] == "history.availability_daily"
    command_sql = mock_command.call_args.args[3]
    json_key, parquet_key = poller.rollup_object_keys(day)
    assert "INSERT INTO FUNCTION s3(" in command_sql
    assert parquet_key in command_sql
    assert "fleet-availability" in command_sql
    assert "'Parquet'" in command_sql
    assert "FROM history.availability_daily FINAL WHERE day = " in command_sql
    assert ("fleet-availability", json_key) in s3.objects


def test_rollup_one_day_only_json_present_runs_parquet_export_only():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, _parquet_key = poller.rollup_object_keys(day)
    s3.objects[("fleet-availability", json_key)] = b"{}"
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "_clickhouse_query", return_value=[]),
        patch.object(poller, "_clickhouse_insert"),
        patch.object(poller, "_clickhouse_command") as mock_command,
    ):
        result = poller.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    mock_command.assert_called_once()
    assert s3.objects[("fleet-availability", json_key)] == b"{}"


def test_rollup_one_day_only_parquet_present_runs_json_put_only():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, parquet_key = poller.rollup_object_keys(day)
    s3.objects[("fleet-availability", parquet_key)] = b"parquet-bytes"
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "_clickhouse_query", return_value=[]),
        patch.object(poller, "_clickhouse_insert"),
        patch.object(poller, "_clickhouse_command") as mock_command,
    ):
        result = poller.rollup_one_day(_rollup_config(), s3, tz, day)
    assert result == "written"
    mock_command.assert_not_called()
    assert ("fleet-availability", json_key) in s3.objects
    assert s3.objects[("fleet-availability", parquet_key)] == b"parquet-bytes"


def test_rollup_one_day_invalid_document_raises_rollup_error_and_nothing_is_put():
    s3 = _FakeS3()
    day = datetime.date(2026, 9, 27)
    json_key, parquet_key = poller.rollup_object_keys(day)
    s3.objects[("fleet-availability", parquet_key)] = b"parquet-bytes"
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "_clickhouse_query", return_value=[]),
        patch.object(poller, "_clickhouse_insert"),
        patch.object(poller, "availability_document_problems", return_value=["bad schema_version"]),
        pytest.raises(poller.RollupError),
    ):
        poller.rollup_one_day(_rollup_config(), s3, tz, day)
    assert ("fleet-availability", json_key) not in s3.objects


def test_export_parquet_access_key_with_quote_raises_without_request():
    config = _rollup_config(s3_access_key="bad'key")
    parquet_key = "availability_parquet/date=2026-09-27/availability.parquet"
    with (
        patch.object(poller, "_clickhouse_command") as mock_command,
        pytest.raises(poller.ClickHouseError),
    ):
        poller.export_parquet(config, datetime.date(2026, 9, 27), parquet_key)
    mock_command.assert_not_called()


def test_export_parquet_secret_key_with_quote_raises_without_request():
    config = _rollup_config(s3_secret_key="bad'secret")
    parquet_key = "availability_parquet/date=2026-09-27/availability.parquet"
    with (
        patch.object(poller, "_clickhouse_command") as mock_command,
        pytest.raises(poller.ClickHouseError),
    ):
        poller.export_parquet(config, datetime.date(2026, 9, 27), parquet_key)
    mock_command.assert_not_called()


def test_run_rollups_continues_past_a_failing_day():
    config = _rollup_config()
    s3 = _FakeS3()
    with (
        patch.object(poller, "fetch_first_data_day", return_value=datetime.date(2026, 9, 20)),
        patch.object(
            poller,
            "rollup_one_day",
            side_effect=[poller.RollupError("boom"), "written", "skipped"],
        ),
    ):
        written, failures = poller.run_rollups(config, s3, datetime.date(2026, 9, 23))
    assert failures == 1
    assert len(written) == 1


def test_fetch_first_data_day_returns_none_when_table_empty():
    config = _rollup_config()
    with patch.object(poller, "_clickhouse_query", return_value=[{"d": "1970-01-01", "n": "0"}]):
        assert poller.fetch_first_data_day(config, "Asia/Singapore") is None


def test_fetch_first_data_day_returns_date_when_table_has_rows():
    config = _rollup_config()
    with patch.object(poller, "_clickhouse_query", return_value=[{"d": "2026-09-20", "n": "1000"}]):
        assert poller.fetch_first_data_day(config, "Asia/Singapore") == datetime.date(2026, 9, 20)


# --- build_hosts_query / select_host_columns --------------------------------


def test_build_hosts_query_produces_exact_lql_text():
    assert poller.build_hosts_query(["name", "state"]) == (
        "GET hosts\nColumns: name state\nOutputFormat: json\n\n"
    )


def test_select_host_columns_orders_required_then_available_optional():
    result = poller.select_host_columns({"name", "state", "parents"})
    assert result == ["name", "state", "parents"]


def test_select_host_columns_raises_on_missing_required_column():
    try:
        poller.select_host_columns({"state"})
    except poller.LivestatusError as exc:
        assert "name" in str(exc)
    else:
        raise AssertionError("expected LivestatusError")


def test_select_host_columns_omits_unavailable_optional_columns():
    result = poller.select_host_columns({"name", "state"})
    assert result == ["name", "state"]


# --- available_host_columns ---------------------------------------------------


def test_available_host_columns_sends_expected_lql_query():
    sock = _fake_connection(b'[["name"], ["state"]]')
    with patch("socket.create_connection", return_value=sock):
        result = poller.available_host_columns("checkmk", poller.DEFAULT_LIVESTATUS_PORT, 10)
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    assert result == {"name", "state"}


# --- available_service_columns / select_service_columns / build_services_query ---


def test_build_services_query_produces_exact_lql_text():
    assert poller.build_services_query(["host_name", "description", "state"]) == (
        "GET services\nColumns: host_name description state\nOutputFormat: json\n\n"
    )


def test_available_service_columns_sends_expected_lql_query():
    sock = _fake_connection(b'[["host_name"], ["description"], ["state"]]')
    with patch("socket.create_connection", return_value=sock):
        result = poller.available_service_columns("checkmk", poller.DEFAULT_LIVESTATUS_PORT, 10)
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == "GET columns\nColumns: name\nFilter: table = services\nOutputFormat: json\n\n"
    assert result == {"host_name", "description", "state"}


def test_select_service_columns_orders_required_then_available_optional():
    result = poller.select_service_columns({"host_name", "description", "state", "plugin_output", "perf_data"})
    assert result == ["host_name", "description", "state", "plugin_output", "perf_data"]


def test_select_service_columns_no_exception_when_perf_data_absent():
    result = poller.select_service_columns({"host_name", "description", "state"})
    assert result == ["host_name", "description", "state"]


def test_select_service_columns_raises_on_missing_required_column():
    try:
        poller.select_service_columns({"host_name", "state"})
    except poller.LivestatusError as exc:
        assert "description" in str(exc)
    else:
        raise AssertionError("expected LivestatusError")


def test_select_service_columns_omits_unavailable_optional_columns():
    result = poller.select_service_columns({"host_name", "description", "state", "plugin_output"})
    assert result == ["host_name", "description", "state", "plugin_output"]


# --- query_devices --------------------------------------------------------------


def test_query_devices_parses_full_row_into_device_snapshot():
    columns = [
        "name",
        "state",
        "scheduled_downtime_depth",
        "acknowledged",
        "worst_service_state",
        "parents",
        "tags",
        "alias",
    ]
    row = [
        "web1",
        0,
        1,
        True,
        2,
        ["switch-01"],
        {"device_type": "server"},
        "Web Server 1",
    ]
    sock = _fake_connection(json.dumps([row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10, folders={"web1": "vlan10"}
        )
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.id == "web1"
    assert snapshot.state == "CRIT"
    assert snapshot.in_downtime is True
    assert snapshot.acknowledged is True
    assert snapshot.device_type == "server"
    assert snapshot.folder == "vlan10"
    assert snapshot.parents == ["switch-01"]
    assert snapshot.alias == "Web Server 1"


def test_query_devices_folder_maps_to_empty_string_when_host_absent_from_mapping():
    snapshots = None
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, folders={"other-host": "vlan10"}
        )
    assert snapshots[0].folder == ""


def test_query_devices_folder_maps_to_empty_string_when_no_mapping_supplied():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
    assert snapshots[0].folder == ""


def test_query_devices_wr07_site_named_wato_produces_correct_folder():
    # Regression test for WR-07: the retired filename-string derive_folder()
    # located a literal "wato" segment in the Livestatus filename path,
    # which broke when the Checkmk site id was itself "wato" (a second,
    # unrelated "wato" segment then appears earlier in the same path).
    # The REST-sourced folder mapping has no filesystem-path parsing at
    # all, so a site id of "wato" cannot perturb it.
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, folders={"web1": "vlan10"}
        )
    assert snapshots[0].folder == "vlan10"


def test_query_devices_host_config_fills_map_position_and_unmanaged():
    sock = _fake_connection(b'[["sw1", 0]]')
    host_config = {"sw1": poller.HostConfigInfo(folder="vlan10", map_position="120,-40", unmanaged=True)}
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, host_config=host_config
        )
    assert snapshots[0].map_position == "120,-40"
    assert snapshots[0].unmanaged is True


def test_query_devices_host_config_defaults_when_host_missing_from_mapping():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, host_config={"other-host": poller.HostConfigInfo()}
        )
    assert snapshots[0].map_position is None
    assert snapshots[0].unmanaged is False


def test_query_devices_carries_phase14_labels_from_host_config():
    sock = _fake_connection(b'[["h1", 0]]')
    host_config = {
        "h1": poller.HostConfigInfo(
            criticality="critical", depends_on=["h2"], service_criticality={"cron": "high"}
        )
    }
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, host_config=host_config
        )
    assert snapshots[0].criticality == "critical"
    assert snapshots[0].depends_on == ["h2"]
    assert snapshots[0].service_criticality == {"cron": "high"}


def test_query_devices_phase14_labels_default_when_host_missing_from_host_config():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, host_config={"other-host": poller.HostConfigInfo()}
        )
    assert snapshots[0].criticality == poller.DEFAULT_CRITICALITY
    assert snapshots[0].depends_on == []
    assert snapshots[0].service_criticality == {}


def test_query_devices_host_config_defaults_when_no_mapping_supplied():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
    assert snapshots[0].map_position is None
    assert snapshots[0].unmanaged is False


def test_query_devices_uses_safe_defaults_when_optional_columns_absent():
    columns = ["name", "state"]
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.in_downtime is False
    assert snapshot.acknowledged is False
    assert snapshot.parents == []
    assert snapshot.device_type == "unknown"
    assert snapshot.folder == ""
    assert snapshot.alias == ""


def test_query_devices_alias_defaults_to_empty_string_when_column_absent():
    columns = ["name", "state", "tags"]
    sock = _fake_connection(json.dumps([["web1", 0, {}]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_alias_defaults_to_empty_string_when_row_truncated():
    columns = ["name", "state", "tags", "alias"]
    # Row ends before the alias column's position.
    truncated_row = ["web1", 0, {}]
    sock = _fake_connection(json.dumps([truncated_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_alias_coerces_non_string_value_to_empty_string():
    columns = ["name", "state", "alias"]
    sock = _fake_connection(json.dumps([["web1", 0, None]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_optional_host_columns_includes_address():
    assert "address" in poller.OPTIONAL_HOST_COLUMNS


def test_query_devices_address_defaults_to_empty_string_when_column_absent():
    columns = ["name", "state", "tags"]
    sock = _fake_connection(json.dumps([["web1", 0, {}]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].address == ""


def test_query_devices_address_defaults_to_empty_string_when_row_truncated():
    columns = ["name", "state", "tags", "address"]
    # Row ends before the address column's position.
    truncated_row = ["web1", 0, {}]
    sock = _fake_connection(json.dumps([truncated_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].address == ""


def test_query_devices_address_coerces_non_string_value_to_empty_string():
    columns = ["name", "state", "address"]
    sock = _fake_connection(json.dumps([["web1", 0, None]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].address == ""


def test_query_devices_address_carries_through_populated_value():
    columns = ["name", "state", "address"]
    sock = _fake_connection(json.dumps([["router", 0, "192.168.0.1"]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].address == "192.168.0.1"


def test_query_devices_address_is_stripped_of_surrounding_whitespace():
    columns = ["name", "state", "address"]
    sock = _fake_connection(json.dumps([["router", 0, "  192.168.0.1  "]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].address == "192.168.0.1"


def test_query_devices_staleness_defaults_to_none_when_column_absent():
    columns = ["name", "state", "tags"]
    sock = _fake_connection(json.dumps([["web1", 0, {}]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].staleness is None


def test_query_devices_staleness_defaults_to_none_when_row_truncated():
    columns = ["name", "state", "tags", "staleness"]
    # Row ends before the staleness column's position.
    truncated_row = ["web1", 0, {}]
    sock = _fake_connection(json.dumps([truncated_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].staleness is None


def test_query_devices_staleness_defaults_to_none_when_value_non_numeric():
    columns = ["name", "state", "staleness"]
    sock = _fake_connection(json.dumps([["web1", 0, "not-a-number"]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].staleness is None


def test_query_devices_staleness_carries_through_numeric_value_as_float():
    columns = ["name", "state", "staleness"]
    sock = _fake_connection(json.dumps([["web1", 0, 4.5]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].staleness == 4.5


def test_optional_host_columns_includes_last_state_change():
    assert "last_state_change" in poller.OPTIONAL_HOST_COLUMNS


def test_query_devices_parses_last_state_change():
    columns = ["name", "state", "last_state_change"]
    sock = _fake_connection(json.dumps([["web1", 0, 1790000000]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].last_state_change == 1790000000


def test_query_devices_last_state_change_absent_or_zero_is_none():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
    assert snapshots[0].last_state_change is None

    columns = ["name", "state", "last_state_change"]
    sock = _fake_connection(json.dumps([["web1", 0, 0]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].last_state_change is None

    sock = _fake_connection(json.dumps([["web2", 0, "not-a-number"]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].last_state_change is None


def test_query_devices_host_state_raw_is_unreach_while_state_stays_down():
    # D-17's entire point: state keeps its collapsed "DOWN" meaning while
    # host_state_raw separately distinguishes UNREACHABLE (raw state 2).
    columns = ["name", "state"]
    sock = _fake_connection(json.dumps([["web1", 2]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].state == "DOWN"
    assert snapshots[0].host_state_raw == "UNREACH"


def test_query_devices_skips_topic_unsafe_host_name():
    columns = ["name", "state"]
    sock = _fake_connection(b'[["lan/rogue", 0], ["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    ids = [snapshot.id for snapshot in snapshots]
    assert "lan/rogue" not in ids
    assert "web1" in ids


def test_query_devices_survives_row_truncated_after_worst_service_state():
    # Regression test for CR-01: `parents`/`tags`/`acknowledged` extractions
    # were previously unguarded `row[index[...]]` lookups, so a row shorter
    # than the requested column list raised an uncaught IndexError that
    # escaped the poll loop entirely instead of being skipped/defaulted per
    # the function's own documented contract.
    columns = [
        "name",
        "state",
        "scheduled_downtime_depth",
        "acknowledged",
        "worst_service_state",
        "parents",
        "tags",
    ]
    # Present through worst_service_state (index 4); parents/tags missing.
    truncated_row = ["web1", 0, 1, True, 2]
    full_row = [
        "web2",
        0,
        1,
        True,
        2,
        ["switch-01"],
        {"device_type": "server"},
    ]
    sock = _fake_connection(json.dumps([truncated_row, full_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        # Must not raise IndexError: the truncated row falls back to safe
        # defaults for its missing trailing columns rather than crashing.
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    ids = [snapshot.id for snapshot in snapshots]
    assert "web1" in ids
    assert "web2" in ids
    web1 = next(snapshot for snapshot in snapshots if snapshot.id == "web1")
    assert web1.in_downtime is True
    assert web1.acknowledged is True
    assert web1.parents == []
    assert web1.device_type == "unknown"
    assert web1.folder == ""


def test_query_devices_raises_livestatus_error_on_malformed_json():
    sock = _fake_connection(b"not-json{{{")
    with patch("socket.create_connection", return_value=sock):
        try:
            poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
        except poller.LivestatusError:
            pass
        else:
            raise AssertionError("expected LivestatusError")


def test_query_devices_raises_livestatus_error_on_socket_failure():
    with patch("socket.create_connection", side_effect=OSError("connection refused")):
        try:
            poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
        except poller.LivestatusError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected LivestatusError")


def test_query_devices_connects_with_configured_timeout():
    sock = _fake_connection(b"[]")
    with patch("socket.create_connection", return_value=sock) as mock_connect:
        poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 7.5)
    mock_connect.assert_called_once_with(("checkmk", poller.DEFAULT_LIVESTATUS_PORT), timeout=7.5)


# --- query_services / ServiceSnapshot ----------------------------------------


def test_query_services_parses_full_row_into_service_snapshot():
    columns = ["host_name", "description", "state", "plugin_output", "perf_data"]
    row = ["web1", "CPU utilization", 1, "WARN - util 85%", "util=85;80;90;0;100"]
    sock = _fake_connection(json.dumps([row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_services("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot == poller.ServiceSnapshot(
        host_name="web1",
        description="CPU utilization",
        state="WARN",
        state_raw=1,
        plugin_output="WARN - util 85%",
        perf_data=snapshot.perf_data,
    )
    assert snapshot.perf_data["util"]["crit"] == 90.0


def test_query_services_skips_malformed_row_keeps_valid_sibling():
    columns = ["host_name", "description", "state"]
    rows = [
        ["web1", "PING", "not-a-number"],
        ["web2", "PING", 0],
    ]
    sock = _fake_connection(json.dumps(rows).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_services("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert len(snapshots) == 1
    assert snapshots[0].host_name == "web2"


def test_query_services_required_only_columns_degrade_optional_fields():
    columns = ["host_name", "description", "state"]
    sock = _fake_connection(json.dumps([["web1", "PING", 0]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_services("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].plugin_output == ""
    assert snapshots[0].perf_data == {}


def test_query_services_empty_body_returns_empty_list():
    sock = _fake_connection(b"")
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_services(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["host_name", "description", "state"], 10
        )
    assert snapshots == []


def test_query_services_malformed_json_raises_livestatus_error():
    sock = _fake_connection(b"not json")
    with patch("socket.create_connection", return_value=sock):
        try:
            poller.query_services(
                "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["host_name", "description", "state"], 10
            )
        except poller.LivestatusError:
            pass
        else:
            raise AssertionError("expected LivestatusError")


def test_query_services_skips_host_failing_publishable_device_id():
    columns = ["host_name", "description", "state"]
    rows = [
        ["lan/rogue", "PING", 0],
        ["web2", "PING", 0],
    ]
    sock = _fake_connection(json.dumps(rows).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_services("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert [s.host_name for s in snapshots] == ["web2"]


# --- classify_host_services / services_signature -----------------------------


def _service(host_name, description, state, plugin_output="", perf_data=None):
    state_raw = {"OK": 0, "WARN": 1, "CRIT": 2, "UNKNOWN": 3}[state]
    return poller.ServiceSnapshot(
        host_name=host_name,
        description=description,
        state=state,
        state_raw=state_raw,
        plugin_output=plugin_output,
        perf_data=perf_data or {},
    )


def test_classify_host_services_full_fixture_computes_gauges_smart_and_rows():
    services = [
        _service(
            "web1",
            "CPU utilization",
            "OK",
            perf_data={"util": {"value": 12.5, "warn": 80.0, "crit": 90.0, "min": 0.0, "max": 100.0}},
        ),
        _service(
            "web1",
            "Memory",
            "OK",
            perf_data={
                "mem_used_percent": {"value": 45.0, "warn": 80.0, "crit": 90.0, "min": None, "max": None}
            },
        ),
        _service(
            "web1",
            "Filesystem /",
            "OK",
            perf_data={
                "fs_used_percent": {"value": 55.0, "warn": 80.0, "crit": 90.0, "min": None, "max": None}
            },
        ),
        _service(
            "web1",
            "Filesystem /boot",
            "WARN",
            perf_data={
                "fs_used_percent": {"value": 82.0, "warn": 80.0, "crit": 90.0, "min": None, "max": None}
            },
        ),
        _service("web1", "SMART /dev/sda Stats", "OK"),
        _service("web1", "Temperature SMART /dev/sda", "OK"),
        _service("web1", "Systemd Service cron", "OK"),
        _service("web1", "Systemd Service Summary", "OK"),
        _service("web1", "PING", "OK"),
    ]

    gauge_fields, service_rows = poller.classify_host_services(services)

    assert gauge_fields["cpu_percent"] == 12.5
    assert gauge_fields["cpu_warn"] == 80.0
    assert gauge_fields["cpu_crit"] == 90.0
    assert gauge_fields["ram_percent"] == 45.0
    assert gauge_fields["ram_warn"] == 80.0
    assert gauge_fields["ram_crit"] == 90.0
    assert gauge_fields["disk_percent"] == 55.0
    assert gauge_fields["disk_warn"] == 80.0
    assert gauge_fields["disk_crit"] == 90.0
    assert gauge_fields["disk_other_worst_percent"] == 82.0
    assert gauge_fields["disk_other_worst_warn"] == 80.0
    assert gauge_fields["disk_other_worst_crit"] == 90.0
    assert gauge_fields["disk_other_worst_mount"] == "/boot"
    assert gauge_fields["smart_total"] == 1
    assert gauge_fields["smart_failing"] == 0
    descriptions = [row["description"] for row in service_rows]
    assert descriptions == ["PING", "Systemd Service cron", "Temperature SMART /dev/sda"]
    assert "Systemd Service Summary" not in descriptions


def test_classify_host_services_snmp_only_host_yields_all_gauge_keys_present_and_none():
    services = [_service("snmp1", "PING", "OK")]

    gauge_fields, service_rows = poller.classify_host_services(services)

    assert set(gauge_fields.keys()) == {
        "cpu_percent",
        "cpu_warn",
        "cpu_crit",
        "ram_percent",
        "ram_warn",
        "ram_crit",
        "disk_percent",
        "disk_warn",
        "disk_crit",
        "disk_other_worst_percent",
        "disk_other_worst_warn",
        "disk_other_worst_crit",
        "disk_other_worst_mount",
        "smart_total",
        "smart_failing",
    }
    assert all(value is None for value in gauge_fields.values())
    assert [row["description"] for row in service_rows] == ["PING"]


def test_classify_host_services_empty_list_returns_all_none_gauges_and_no_rows():
    gauge_fields, service_rows = poller.classify_host_services([])
    assert gauge_fields["cpu_percent"] is None
    assert gauge_fields["ram_percent"] is None
    assert gauge_fields["disk_percent"] is None
    assert gauge_fields["disk_other_worst_percent"] is None
    assert gauge_fields["smart_total"] is None
    assert gauge_fields["smart_failing"] is None
    assert service_rows == []


def test_classify_host_services_smart_failing_counts_warn_and_crit_not_unknown():
    services = [
        _service("web1", "SMART /dev/sda Stats", "OK"),
        _service("web1", "SMART /dev/sdb Stats", "WARN"),
        _service("web1", "SMART /dev/sdc Stats", "CRIT"),
        _service("web1", "SMART /dev/sdd Stats", "UNKNOWN"),
    ]
    gauge_fields, _ = poller.classify_host_services(services)
    assert gauge_fields["smart_total"] == 4
    assert gauge_fields["smart_failing"] == 2


def test_services_signature_order_independent_and_excludes_plugin_output():
    rows_a = [
        {"description": "PING", "state": "OK", "plugin_output": "OK - up"},
        {"description": "cron", "state": "OK", "plugin_output": "OK - running"},
    ]
    rows_b_diff_output_only = [
        {"description": "cron", "state": "OK", "plugin_output": "OK - running 5 days"},
        {"description": "PING", "state": "OK", "plugin_output": "OK - up 2ms"},
    ]
    assert poller.services_signature(rows_a) == poller.services_signature(rows_b_diff_output_only)


def test_services_signature_differs_when_first_output_arrives():
    # Regression (2026-10-02): a pending service publishes as OK with empty
    # output; its first result (still OK, now with text) must republish, or
    # the dashboard's Output column stays blank.
    rows_pending = [{"description": "PING", "state": "OK", "plugin_output": ""}]
    rows_checked = [{"description": "PING", "state": "OK", "plugin_output": "OK - 198.51.100.3 rta 0.412ms lost 0%"}]
    assert poller.services_signature(rows_pending) != poller.services_signature(rows_checked)


def test_services_signature_differs_on_state_change():
    rows_a = [{"description": "PING", "state": "OK", "plugin_output": ""}]
    rows_b = [{"description": "PING", "state": "CRIT", "plugin_output": ""}]
    assert poller.services_signature(rows_a) != poller.services_signature(rows_b)


def test_services_signature_differs_on_row_added():
    rows_a = [{"description": "PING", "state": "OK", "plugin_output": ""}]
    rows_b = [
        {"description": "PING", "state": "OK", "plugin_output": ""},
        {"description": "cron", "state": "OK", "plugin_output": ""},
    ]
    assert poller.services_signature(rows_a) != poller.services_signature(rows_b)


# --- MQTT client lifecycle and publish helpers ------------------------------


def _make_config(**overrides) -> "poller.PollerConfig":
    defaults = {
        "livestatus_host": "checkmk",
        "livestatus_port": poller.DEFAULT_LIVESTATUS_PORT,
        "mqtt_host": "mosquitto",
        "mqtt_port": poller.DEFAULT_MQTT_PORT,
        "mqtt_username": "poller",
        "mqtt_password": "secret",
        "poll_interval_seconds": 60,
        "events_max_entries": 3,
        "reconcile_timeout_seconds": 5.0,
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return poller.PollerConfig(**defaults)


def test_build_mqtt_client_will_set_before_connect_with_offline_payload():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        result = poller.build_mqtt_client(_make_config())

    assert result is mock_client
    call_names = [name for name, _args, _kwargs in mock_client.mock_calls]
    assert call_names.index("will_set") < call_names.index("connect")

    args, kwargs = mock_client.will_set.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_POLLER_STATUS)
    assert json.loads(kwargs["payload"]) == {"status": "offline"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_build_mqtt_client_configures_reconnect_backoff_and_starts_loop():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config())

    mock_client.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=120)
    mock_client.loop_start.assert_called_once()


def test_build_mqtt_client_uses_version2_callback_api():
    with patch.object(poller, "mqtt") as mock_mqtt:
        poller.build_mqtt_client(_make_config())

    mock_mqtt.Client.assert_called_once_with(mock_mqtt.CallbackAPIVersion.VERSION2)


def test_build_mqtt_client_on_connect_publishes_online_birth_message():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config())
        on_connect = mock_client.on_connect
        mock_client.publish.reset_mock()
        on_connect(mock_client, None, {}, 0, None)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_POLLER_STATUS)
    payload = json.loads(args[1])
    assert payload["status"] == "online"
    assert payload["last_poll"] is None
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_shutdown_mqtt_client_publishes_offline_before_disconnecting():
    # Regression test for CR-02: a graceful client.disconnect() suppresses
    # the LWT, so every intentional shutdown path must explicitly publish
    # the offline status itself before stopping the loop/disconnecting.
    mock_client = MagicMock()

    poller.shutdown_mqtt_client(mock_client)

    call_names = [name for name, _args, _kwargs in mock_client.mock_calls]
    assert "publish" in call_names
    assert call_names.index("publish") < call_names.index("loop_stop")
    assert call_names.index("loop_stop") < call_names.index("disconnect")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_POLLER_STATUS)
    assert json.loads(args[1]) == {"status": "offline"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_device_status_uses_qos0_and_exact_payload_keys():
    mock_client = MagicMock()
    snapshot = poller.DeviceSnapshot(
        id="web1",
        state="OK",
        in_downtime=False,
        acknowledged=False,
        device_type="server",
        folder="vlan10",
        parents=[],
        alias="Web Server 1",
        address="192.168.0.10",
    )
    poller.publish_device_status(mock_client, snapshot, "2026-09-06T00:00:00+00:00")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == "sites/testsite/lan/devices/web1/status"
    payload = json.loads(args[1])
    assert set(payload.keys()) == {
        "id",
        "state",
        "in_downtime",
        "acknowledged",
        "device_type",
        "folder",
        "alias",
        "address",
        "staleness",
        "host_state_raw",
        "timestamp",
    }
    assert payload["alias"] == "Web Server 1"
    assert payload["address"] == "192.168.0.10"
    assert kwargs["qos"] == 0
    assert kwargs["retain"] is True


def test_publish_device_status_with_gauge_fields_adds_them_to_existing_payload():
    mock_client = MagicMock()
    snapshot = poller.DeviceSnapshot(
        id="web1",
        state="OK",
        in_downtime=False,
        acknowledged=False,
        device_type="server",
        folder="vlan10",
        parents=[],
        alias="Web Server 1",
    )
    gauge_fields = {"cpu_percent": 12.5, "cpu_warn": 80.0, "cpu_crit": 90.0}

    poller.publish_device_status(
        mock_client, snapshot, "2026-09-06T00:00:00+00:00", gauge_fields=gauge_fields
    )

    args, _ = mock_client.publish.call_args
    payload = json.loads(args[1])
    assert payload["cpu_percent"] == 12.5
    assert payload["id"] == "web1"  # pre-existing keys still present


def test_publish_topology_uses_qos1_and_devices_envelope():
    mock_client = MagicMock()
    nodes = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    poller.publish_topology(mock_client, nodes, "2026-09-06T00:00:00+00:00")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_TOPOLOGY)
    payload = json.loads(args[1])
    assert payload == {"devices": nodes, "timestamp": "2026-09-06T00:00:00+00:00"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_events_publishes_full_array():
    mock_client = MagicMock()
    entries = [{"timestamp": "t1", "device_id": "web1", "event": "added", "from": None, "to": "OK"}]
    poller.publish_events(mock_client, entries)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_EVENTS)
    assert json.loads(args[1]) == entries
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_services_uses_qos1_and_bare_array():
    mock_client = MagicMock()
    rows = [{"description": "PING", "state": "OK", "plugin_output": "OK - up"}]
    poller.publish_services(mock_client, "web1", rows)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == "sites/testsite/lan/devices/web1/services"
    assert json.loads(args[1]) == rows
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_tombstone_clears_all_four_per_device_topics():
    mock_client = MagicMock()
    poller.publish_tombstone(mock_client, "web1")

    calls = mock_client.publish.call_args_list
    assert len(calls) == 4
    topics = {call.args[0] for call in calls}
    assert topics == {
        "sites/testsite/lan/devices/web1/status",
        "sites/testsite/lan/devices/web1/history",
        "sites/testsite/lan/devices/web1/services",
        "sites/testsite/lan/devices/web1/service_history",
    }
    for call in calls:
        assert call.kwargs["payload"] is None
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1


def test_publish_poller_status_payload_shape():
    mock_client = MagicMock()
    poller.publish_poller_status(mock_client, since="t0", last_poll="t1", device_count=5)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_POLLER_STATUS)
    payload = json.loads(args[1])
    assert payload == {"status": "online", "since": "t0", "last_poll": "t1", "device_count": 5}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_json_swallows_oserror_from_client():
    mock_client = MagicMock()
    mock_client.publish.side_effect = OSError("broker down")
    poller.publish_events(mock_client, [{"event": "added"}])  # must not raise


# --- parse_topology_payload / parse_events_payload --------------------------


def test_parse_topology_payload_empty_returns_empty_dict():
    assert poller.parse_topology_payload(b"") == {}


def test_parse_topology_payload_parses_devices_keyed_by_id():
    payload = json.dumps(
        {
            "devices": [
                {
                    "id": "a",
                    "parents": [],
                    "device_type": "server",
                    "folder": "",
                    "alias": "",
                    "map_position": "0,0",
                    "unmanaged": False,
                }
            ],
            "timestamp": "t",
        }
    ).encode()
    assert poller.parse_topology_payload(payload) == {
        "a": {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "",
            "alias": "",
            "map_position": "0,0",
            "unmanaged": False,
            "criticality": poller.DEFAULT_CRITICALITY,
            "service_criticality": {},
            "depends_on": [],
        }
    }


def test_parse_topology_payload_malformed_json_returns_empty_dict():
    assert poller.parse_topology_payload(b"not-json{{{") == {}


# Regression: a retained topology message written by a PRE-Phase-10 poller has
# no `alias` key. Before this was fixed, the first cycle after an upgrade blew
# up with `KeyError: 'alias'` inside topology_signature() — and because the
# retained message is re-read on every start, `restart: unless-stopped` turned
# that into a crash-loop. Caught on a live deployment at Phase 10's checkpoint;
# the payload is valid JSON, so the malformed-JSON guard above never saw it.
def test_parse_topology_payload_backfills_fields_missing_from_older_schema():
    payload = json.dumps(
        {"devices": [{"id": "a", "parents": ["p"], "device_type": "server", "folder": "/f"}]}
    ).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["alias"] == ""
    # Pre-existing fields must survive untouched.
    assert restored["a"]["parents"] == ["p"]
    assert restored["a"]["device_type"] == "server"
    assert restored["a"]["folder"] == "/f"


# 2026-09 (plan 13-04): the same crash-loop class, this time for the two
# fields Phase 13 adds -- a retained payload written by a pre-13-04 poller
# has neither `map_position` nor `unmanaged`.
def test_parse_topology_payload_backfills_map_position_and_unmanaged_missing_from_older_schema():
    payload = json.dumps(
        {"devices": [{"id": "a", "parents": [], "device_type": "server", "folder": "/f", "alias": ""}]}
    ).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["map_position"] is None
    assert restored["a"]["unmanaged"] is False


def test_parse_topology_payload_coerces_wrong_type_map_position_and_unmanaged():
    payload = json.dumps(
        {
            "devices": [
                {
                    "id": "a",
                    "parents": [],
                    "device_type": "server",
                    "folder": "/f",
                    "alias": "",
                    "map_position": 123,
                    "unmanaged": "yes",
                }
            ]
        }
    ).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["map_position"] is None
    assert restored["a"]["unmanaged"] is False


def test_topology_signature_survives_node_restored_from_older_schema():
    """The exact crash: signature-comparing fresh nodes against restored ones."""
    restored = poller.parse_topology_payload(
        json.dumps({"devices": [{"id": "a", "device_type": "server", "folder": "/f"}]}).encode()
    )
    fresh = [{"id": "a", "parents": [], "device_type": "server", "folder": "/f", "alias": ""}]
    # Must not raise, and an alias-less old node must compare equal to a fresh
    # node that has no alias either — no spurious republish on every restart.
    assert poller.topology_signature(fresh) == poller.topology_signature(list(restored.values()))


# Regression (CR-06, Phase 10 code review): the first crash-loop fix backfilled
# missing keys but not wrong types, so these malformed-but-valid-JSON retained
# payloads still broke the cold-start-not-crash-loop contract.
def test_parse_topology_payload_skips_node_with_non_str_id():
    """A list id raised `TypeError: unhashable type` inside the parser itself."""
    payload = json.dumps({"devices": [{"id": ["x"]}, {"id": "good"}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert list(restored) == ["good"]


def test_parse_topology_payload_coerces_string_parents_to_empty_list():
    """`parents: "router1"` made topology_signature sort a string into chars."""
    payload = json.dumps({"devices": [{"id": "a", "parents": "router1"}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["parents"] == []
    sig = poller.topology_signature(list(restored.values()))
    assert sig == (
        ("a", (), poller.UNKNOWN_DEVICE_TYPE, "", "", None, False, poller.DEFAULT_CRITICALITY, (), ()),
    )


def test_parse_topology_payload_coerces_non_str_folder_and_alias():
    payload = json.dumps({"devices": [{"id": "a", "folder": 123, "alias": None}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["folder"] == ""
    assert restored["a"]["alias"] == ""


def test_topology_signature_differs_when_restored_node_gains_an_alias():
    """One republish after an upgrade that adds an alias is correct, not noise."""
    restored = poller.parse_topology_payload(
        json.dumps({"devices": [{"id": "a", "device_type": "server", "folder": "/f"}]}).encode()
    )
    fresh = [{"id": "a", "parents": [], "device_type": "server", "folder": "/f", "alias": "core-sw"}]
    assert poller.topology_signature(fresh) != poller.topology_signature(list(restored.values()))


def test_normalise_restored_node_backfills_phase14_fields():
    """A pre-14-07 retained node (no criticality/service_criticality/depends_on keys)."""
    node = poller._normalise_restored_node({"id": "a", "device_type": "server", "folder": "/f"})
    assert node["criticality"] == poller.DEFAULT_CRITICALITY
    assert node["service_criticality"] == {}
    assert node["depends_on"] == []


def test_normalise_restored_node_rejects_wrong_typed_phase14_fields():
    node = poller._normalise_restored_node(
        {
            "id": "a",
            "device_type": "server",
            "folder": "/f",
            "criticality": 3,
            "service_criticality": "x",
            "depends_on": "a,b",
        }
    )
    assert node["criticality"] == poller.DEFAULT_CRITICALITY
    assert node["service_criticality"] == {}
    assert node["depends_on"] == []

    node2 = poller._normalise_restored_node({"id": "a", "depends_on": [1, "b"]})
    assert node2["depends_on"] == []


def test_normalise_restored_node_upgrade_republishes_topology_once_and_never_raises():
    restored = poller.parse_topology_payload(
        json.dumps({"devices": [{"id": "a", "device_type": "server", "folder": "/f"}]}).encode()
    )
    fresh_same = [
        {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "/f",
            "alias": "",
            "map_position": None,
            "unmanaged": False,
            "criticality": poller.DEFAULT_CRITICALITY,
            "service_criticality": {},
            "depends_on": [],
        }
    ]
    # No new labels set: the restored (backfilled) node and a fresh node with
    # the same defaults must compare equal -- no spurious republish.
    assert poller.topology_signature(fresh_same) == poller.topology_signature(list(restored.values()))

    fresh_changed = [{**fresh_same[0], "criticality": "critical"}]
    assert poller.topology_signature(fresh_changed) != poller.topology_signature(list(restored.values()))


def test_parse_events_payload_empty_returns_empty_list():
    assert poller.parse_events_payload(b"") == []


def test_parse_events_payload_parses_list():
    payload = json.dumps([{"event": "added"}]).encode()
    assert poller.parse_events_payload(payload) == [{"event": "added"}]


def test_parse_events_payload_malformed_json_returns_empty_list():
    assert poller.parse_events_payload(b"not-json{{{") == []


# --- reconcile_state ----------------------------------------------------------


def _make_message(topic: str, payload: bytes, retain: bool = True):
    return SimpleNamespace(topic=topic, payload=payload, retain=retain)


def test_reconcile_state_does_not_set_a_will():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    mock_client.will_set.assert_not_called()


def test_reconcile_state_returns_cold_start_state_when_nothing_retained():
    with patch.object(poller, "mqtt"):
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.previous_nodes == {}
    assert state.last_status == {}
    assert state.events == []


def test_reconcile_state_seeds_previous_nodes_from_retained_topology():
    topology_payload = json.dumps(
        {"devices": [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}], "timestamp": "t"}
    ).encode()

    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.site_topic(poller.TOPIC_TOPOLOGY):
                mock_client.on_message(
                    mock_client, None, _make_message(poller.site_topic(poller.TOPIC_TOPOLOGY), topology_payload)
                )

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.previous_nodes == {
        "a": {
            "id": "a",
            "parents": [],
            "device_type": "server",
            "folder": "",
            "alias": "",
            "map_position": None,
            "unmanaged": False,
            "criticality": poller.DEFAULT_CRITICALITY,
            "service_criticality": {},
            "depends_on": [],
        }
    }


def test_host_config_from_topology_keeps_labels_from_retained_topology():
    # Regression for 14-REVIEW WR-06: the startup host-config cache must carry the retained
    # labels, so a REST failure on the first cycle doesn't reset them all to defaults.
    payload = json.dumps(
        {
            "devices": [
                {
                    "id": "a",
                    "parents": [],
                    "device_type": "server",
                    "folder": "lan",
                    "alias": "",
                    "map_position": "10,20",
                    "unmanaged": True,
                    "criticality": "critical",
                    "service_criticality": {"PING": "high"},
                    "depends_on": ["b"],
                }
            ],
            "timestamp": "t",
        }
    ).encode()
    config = poller.host_config_from_topology(poller.parse_topology_payload(payload))
    assert config == {
        "a": poller.HostConfigInfo(
            folder="lan",
            map_position="10,20",
            unmanaged=True,
            criticality="critical",
            service_criticality={"PING": "high"},
            depends_on=["b"],
        )
    }
    assert poller.host_config_from_topology({}) == {}


def test_reconcile_state_seeds_previous_incidents_from_retained_incident_topics():
    retained = [
        ("sites/testsite/lan/incidents/incident-x/status", b'{"id": "incident-x"}'),
        ("sites/testsite/lan/incidents/incident-cleared/status", b""),
        (poller.site_topic(poller.TOPIC_TOPOLOGY), b'{"devices": []}'),
    ]

    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.site_topic(poller.TOPIC_TOPOLOGY):
                for msg_topic, payload in retained:
                    mock_client.on_message(mock_client, None, _make_message(msg_topic, payload))

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.previous_incidents == {"incident-x": None}


# --- run_cycle ------------------------------------------------------------------


def _snapshot(
    id_,
    state="OK",
    parents=None,
    device_type="server",
    folder="",
    in_downtime=False,
    acknowledged=False,
    host_state_raw="UP",
    unmanaged=False,
    criticality="low",
    depends_on=None,
    last_state_change=None,
    service_criticality=None,
):
    return poller.DeviceSnapshot(
        id=id_,
        state=state,
        in_downtime=in_downtime,
        acknowledged=acknowledged,
        device_type=device_type,
        folder=folder,
        parents=parents or [],
        host_state_raw=host_state_raw,
        unmanaged=unmanaged,
        criticality=criticality,
        depends_on=depends_on or [],
        service_criticality=service_criticality or {},
        last_state_change=last_state_change,
    )


def _poller_state(previous_nodes=None, last_status=None, events=None):
    return poller.PollerState(
        previous_nodes=previous_nodes or {},
        last_status=last_status or {},
        events=events if events is not None else [],
        since="2026-09-06T00:00:00+00:00",
    )


def _published(mock_client, topic):
    return [call for call in mock_client.publish.call_args_list if call.args[0] == topic]


def test_run_cycle_publishes_one_status_per_snapshot_with_retain():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    status_calls = _published(client, "sites/testsite/lan/devices/a/status") + _published(client, "sites/testsite/lan/devices/b/status")
    assert len(status_calls) == 2
    for call in status_calls:
        assert call.kwargs["retain"] is True


def test_run_cycle_skips_topology_publish_when_unchanged():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    assert _published(client, poller.site_topic(poller.TOPIC_TOPOLOGY)) == []


def test_run_cycle_publishes_topology_on_cold_start():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_publishes_topology_on_reparent():
    client = MagicMock()
    node_a = {"id": "a", "parents": ["x"], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", parents=["y"])])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_republishes_topology_on_criticality_change():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", criticality="high")])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_republishes_topology_on_depends_on_change():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", depends_on=["b"])])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_skips_topology_publish_when_phase14_labels_unchanged():
    client = MagicMock()
    node_a = {
        "id": "a",
        "parents": [],
        "device_type": "server",
        "folder": "",
        "alias": "",
        "map_position": None,
        "unmanaged": False,
        "criticality": "medium",
        "service_criticality": {"cron": "low"},
        "depends_on": ["b"],
    }
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(
        client,
        _make_config(),
        state,
        [_snapshot("a", criticality="medium", depends_on=["b"], service_criticality={"cron": "low"})],
    )

    assert _published(client, poller.site_topic(poller.TOPIC_TOPOLOGY)) == []


def test_run_cycle_publishes_topology_on_add():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_publishes_topology_on_remove():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [])

    assert len(_published(client, poller.site_topic(poller.TOPIC_TOPOLOGY))) == 1


def test_run_cycle_removed_device_tombstones_per_device_topics_and_events():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})
    state.previous_services["a"] = (("PING", "OK"),)

    poller.run_cycle(client, _make_config(), state, [])

    tombstones = [c for c in client.publish.call_args_list if c.kwargs.get("payload", "unset") is None]
    assert {c.args[0] for c in tombstones} == {
        "sites/testsite/lan/devices/a/status",
        "sites/testsite/lan/devices/a/history",
        "sites/testsite/lan/devices/a/services",
        "sites/testsite/lan/devices/a/service_history",
    }
    for call in tombstones:
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1
    assert "a" not in state.last_status
    assert "a" not in state.previous_services

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    assert len(events_calls) == 1
    entry = json.loads(events_calls[0].args[1])[-1]
    assert entry["device_id"] == "a"
    assert entry["event"] == "removed"
    assert entry["from"] == "OK"
    assert entry["to"] is None


def test_run_cycle_added_device_appends_added_event():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b", state="WARN")])

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    assert len(events_calls) == 1
    entries = json.loads(events_calls[0].args[1])
    entry = next(e for e in entries if e["device_id"] == "b")
    assert entry["event"] == "added"
    assert entry["from"] is None
    assert entry["to"] == "WARN"


def test_run_cycle_state_change_appends_event_and_publishes_events_topic():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", state="CRIT")])

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    assert len(events_calls) == 1
    entry = json.loads(events_calls[0].args[1])[-1]
    assert entry["event"] == "state_change"
    assert entry["from"] == "OK"
    assert entry["to"] == "CRIT"


def test_run_cycle_no_changes_publishes_no_history_or_events():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", state="OK")])

    assert _published(client, poller.site_topic(poller.TOPIC_EVENTS)) == []
    assert _published(client, "sites/testsite/lan/devices/a/history") == []


def test_run_cycle_cold_start_emits_no_state_change_events():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    if events_calls:
        entries = json.loads(events_calls[0].args[1])
        assert all(entry["event"] != "state_change" for entry in entries)


def test_run_cycle_truncates_events_to_configured_bound():
    client = MagicMock()
    config = _make_config(events_max_entries=1)
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(
        previous_nodes={"a": node_a},
        last_status={"a": "OK"},
        events=[{"timestamp": "t0", "device_id": "z", "event": "added", "from": None, "to": "OK"}],
    )

    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT")])

    assert len(state.events) <= 1


# --- run_cycle: incidents (PLR-14/PLR-16) ------------------------------------


def test_run_cycle_publishes_new_incident_retained_qos1():
    client = MagicMock()
    state = _poller_state()
    snapshots = [
        _snapshot("sw1", host_state_raw="DOWN"),
        _snapshot("a", host_state_raw="UNREACH", parents=["sw1"]),
    ]

    poller.run_cycle(client, _make_config(), state, snapshots)

    calls = _published(client, "sites/testsite/lan/incidents/incident-sw1/status")
    assert len(calls) == 1
    call = calls[0]
    assert call.kwargs["retain"] is True
    assert call.kwargs["qos"] == 1
    payload = json.loads(call.args[1])
    assert payload["root"] == "sw1"
    assert payload["not_observable"] == ["a"]
    assert "timestamp" in payload
    assert state.previous_incidents["incident-sw1"] == poller.incident_signature(
        {**payload, "id": "incident-sw1"}
    )


def test_run_cycle_incident_worst_criticality_counts_dependents_from_labels():
    """End-to-end (D-05/D-07/D-15): lift1 is UNREACH under DOWN sw1, and screen1
    (UP, criticality "critical") depends_on ["lift1"] -- run_cycle publishes an
    incident with dependents ["screen1"] and worst_criticality "high" (screen1
    is UP, so its "critical" tier counts one tier lower, D-15).
    """
    client = MagicMock()
    state = _poller_state()
    snapshots = [
        _snapshot("sw1", host_state_raw="DOWN"),
        _snapshot("lift1", host_state_raw="UNREACH", parents=["sw1"]),
        _snapshot("screen1", host_state_raw="UP", criticality="critical", depends_on=["lift1"]),
    ]

    poller.run_cycle(client, _make_config(), state, snapshots)

    calls = _published(client, "sites/testsite/lan/incidents/incident-sw1/status")
    assert len(calls) == 1
    payload = json.loads(calls[0].args[1])
    assert payload["dependents"] == ["screen1"]
    assert payload["worst_criticality"] == "high"


def test_run_cycle_does_not_republish_unchanged_incident():
    client = MagicMock()
    state = _poller_state()
    snapshots = [
        _snapshot("sw1", host_state_raw="DOWN"),
        _snapshot("a", host_state_raw="UNREACH", parents=["sw1"]),
    ]

    poller.run_cycle(client, _make_config(), state, snapshots)
    client.reset_mock()
    poller.run_cycle(client, _make_config(), state, snapshots)

    assert _published(client, "sites/testsite/lan/incidents/incident-sw1/status") == []


def test_run_cycle_republishes_incident_when_consequences_change():
    client = MagicMock()
    state = _poller_state()
    snapshots = [
        _snapshot("sw1", host_state_raw="DOWN"),
        _snapshot("a", host_state_raw="UNREACH", parents=["sw1"]),
    ]

    poller.run_cycle(client, _make_config(), state, snapshots)
    client.reset_mock()
    recovered = [_snapshot("sw1", host_state_raw="DOWN"), _snapshot("a", parents=["sw1"])]
    poller.run_cycle(client, _make_config(), state, recovered)

    calls = _published(client, "sites/testsite/lan/incidents/incident-sw1/status")
    assert len(calls) == 1
    payload = json.loads(calls[0].args[1])
    assert payload["not_observable"] == []


def test_run_cycle_tombstones_closed_incident():
    client = MagicMock()
    state = _poller_state()
    poller.run_cycle(client, _make_config(), state, [_snapshot("sw1", host_state_raw="DOWN")])
    client.reset_mock()

    poller.run_cycle(client, _make_config(), state, [_snapshot("sw1")])

    tombstones = [
        call
        for call in client.publish.call_args_list
        if call.args[0] == "sites/testsite/lan/incidents/incident-sw1/status"
        and call.kwargs.get("payload", "unset") is None
    ]
    assert len(tombstones) == 1
    for call in tombstones:
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1
    assert "incident-sw1" not in state.previous_incidents


def test_run_cycle_tombstones_reconciled_incident_that_is_no_longer_open():
    client = MagicMock()
    state = _poller_state()
    state.previous_incidents = {"incident-stale": None}

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    tombstones = [
        call
        for call in client.publish.call_args_list
        if call.args[0] == "sites/testsite/lan/incidents/incident-stale/status"
        and call.kwargs.get("payload", "unset") is None
    ]
    assert len(tombstones) == 1
    assert state.previous_incidents == {}


def test_run_cycle_healthy_fleet_publishes_nothing_on_incident_topics():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b", parents=["a"])])

    incident_calls = [call for call in client.publish.call_args_list if call.args[0].startswith("sites/testsite/lan/incidents/")]
    assert incident_calls == []


# --- run_cycle: services (D-12/D-13) -----------------


def test_run_cycle_identical_services_across_two_cycles_publishes_services_once():
    client = MagicMock()
    state = _poller_state()
    config = _make_config()
    services = [_service("web1", "PING", "OK", plugin_output="OK - up")]

    poller.run_cycle(client, config, state, [_snapshot("web1")], services=services)
    poller.run_cycle(client, config, state, [_snapshot("web1")], services=services)

    assert len(_published(client, "sites/testsite/lan/devices/web1/services")) == 1


def test_run_cycle_plugin_output_only_change_does_not_republish_services():
    client = MagicMock()
    state = _poller_state()
    config = _make_config()
    services_cycle1 = [_service("web1", "PING", "OK", plugin_output="OK - up 1ms")]
    services_cycle2 = [_service("web1", "PING", "OK", plugin_output="OK - up 9ms")]

    poller.run_cycle(client, config, state, [_snapshot("web1")], services=services_cycle1)
    poller.run_cycle(client, config, state, [_snapshot("web1")], services=services_cycle2)

    assert len(_published(client, "sites/testsite/lan/devices/web1/services")) == 1


def test_run_cycle_state_changes_publish_no_history_topics_but_keep_events_and_services():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})
    config = _make_config()

    poller.run_cycle(
        client, config, state, [_snapshot("a")], services=[_service("a", "PING", "OK")]
    )
    client.reset_mock()
    poller.run_cycle(
        client, config, state, [_snapshot("a", state="CRIT")], services=[_service("a", "PING", "CRIT")]
    )

    topics = [c.args[0] for c in client.publish.call_args_list]
    assert not [t for t in topics if t.endswith("/history") or t.endswith("/service_history")]
    events = json.loads(_published(client, poller.site_topic(poller.TOPIC_EVENTS))[0].args[1])
    assert events[-1]["event"] == "state_change"
    assert len(_published(client, "sites/testsite/lan/devices/a/services")) == 1


def test_run_cycle_services_none_publishes_status_but_nothing_on_services_topic():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("web1")], services=None)

    assert len(_published(client, "sites/testsite/lan/devices/web1/status")) == 1
    assert _published(client, "sites/testsite/lan/devices/web1/services") == []


# Regression for D-33 (oldest-events-on-top was reported live, but the shipped
# code is correct): `EventHistory` (dashboard-react/src/components/EventHistory.tsx) reverses
# the published array exactly once, trusting that the poller publishes it
# oldest-first. No prior test pinned array *order* across multiple cycles --
# every existing events test above checks membership or `entries[-1]`, which a
# producer-side order flip would not fail. This asserts the full ordered list.
def test_events_published_oldest_first_across_cycles():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    node_b = {"id": "b", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(
        previous_nodes={"a": node_a, "b": node_b},
        last_status={"a": "OK", "b": "OK"},
    )
    config = _make_config(events_max_entries=10)

    # Cycle 1: only "a" changes state.
    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT"), _snapshot("b", state="OK")])
    # Cycle 2: only "b" changes state.
    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT"), _snapshot("b", state="WARN")])

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    entries = json.loads(events_calls[-1].args[1])
    assert [e["device_id"] for e in entries] == ["a", "b"]


# Regression for D-33, truncation case: `[-config.events_max_entries:]` must
# drop the OLDEST entries and leave the survivors still oldest-first -- the
# same order `renderEvents()` reverses for display.
def test_events_truncation_drops_oldest_and_preserves_order():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    node_b = {"id": "b", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    node_c = {"id": "c", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(
        previous_nodes={"a": node_a, "b": node_b, "c": node_c},
        last_status={"a": "OK", "b": "OK", "c": "OK"},
    )
    config = _make_config(events_max_entries=2)

    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT"), _snapshot("b", state="OK"), _snapshot("c", state="OK")])
    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT"), _snapshot("b", state="WARN"), _snapshot("c", state="OK")])
    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT"), _snapshot("b", state="WARN"), _snapshot("c", state="CRIT")])

    events_calls = _published(client, poller.site_topic(poller.TOPIC_EVENTS))
    entries = json.loads(events_calls[-1].args[1])
    assert [e["device_id"] for e in entries] == ["b", "c"]


def test_run_cycle_publishes_heartbeat_with_refreshed_last_poll_and_device_count():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    status_calls = _published(client, poller.site_topic(poller.TOPIC_POLLER_STATUS))
    assert len(status_calls) == 1
    payload = json.loads(status_calls[0].args[1])
    assert payload["device_count"] == 2
    assert payload["last_poll"] is not None
    assert payload["status"] == "online"


# --- run_forever ---------------------------------------------------------------


class _OneShotEvent:
    """Fake `threading.Event` that reports "stop" after its first `wait()` call.

    Lets a `run_forever` test exercise exactly one loop iteration without
    real signal delivery or real sleeping.
    """

    def __init__(self):
        self._stopped = False

    def is_set(self):
        return self._stopped

    def set(self):
        self._stopped = True

    def wait(self, timeout=None):
        self._stopped = True
        return False


def test_run_forever_survives_livestatus_error_and_does_not_raise():
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", return_value={}),
        patch.object(poller, "query_devices", side_effect=poller.LivestatusError("boom")),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle") as mock_run_cycle,
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    mock_run_cycle.assert_not_called()


def test_run_forever_publishes_offline_status_on_fatal_startup_failure():
    # Regression test for CR-02: the one-time startup column probe failing
    # must still leave the retained poller status as "offline" -- a bare
    # client.disconnect() here previously left it stuck at "online" forever
    # since a graceful disconnect suppresses the LWT. OPS-03's bounded
    # startup retry means this now exercises every retry attempt before
    # the probe is treated as fatal -- poller.time.sleep is patched so the
    # retry backoff doesn't slow the test down.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller, "available_host_columns", side_effect=poller.LivestatusError("no columns")
        ),
        patch.object(poller.time, "sleep"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 1
    status_calls = _published(fake_client, poller.site_topic(poller.TOPIC_POLLER_STATUS))
    assert len(status_calls) == 1
    assert json.loads(status_calls[0].args[1]) == {"status": "offline"}
    fake_client.disconnect.assert_called_once()


def test_run_forever_startup_probe_retries_then_recovers(caplog):
    # OPS-03: a transient startup Livestatus failure (e.g. a Checkmk
    # container restart racing the poller's own start) must not be fatal
    # -- the probe is retried, and a warning (not an error) is logged for
    # the failed attempt.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller,
            "available_host_columns",
            side_effect=[poller.LivestatusError("boom"), {"name", "state"}],
        ),
        patch.object(poller, "fetch_host_config", return_value={}),
        patch.object(poller, "query_devices", return_value=[]),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle"),
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
        patch.object(poller.time, "sleep") as mock_sleep,
        caplog.at_level("WARNING", logger=poller._logger.name),
    ):
        result = poller.run_forever(_make_config())

    assert result != 1
    mock_sleep.assert_called_once_with(poller._STARTUP_RETRY_DELAYS_SECONDS[0])
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert any(
        record.levelname == "WARNING" and "attempt" in record.getMessage()
        for record in caplog.records
    )


def test_run_forever_startup_probe_retry_exhausted_is_fatal():
    # OPS-03: a permanently unreachable Livestatus site must still fail
    # loudly after every retry is exhausted, preserving the pre-existing
    # offline-status/disconnect contract.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller, "available_host_columns", side_effect=poller.LivestatusError("still down")
        ) as mock_probe,
        patch.object(poller.time, "sleep"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 1
    assert mock_probe.call_count == len(poller._STARTUP_RETRY_DELAYS_SECONDS) + 1
    status_calls = _published(fake_client, poller.site_topic(poller.TOPIC_POLLER_STATUS))
    assert len(status_calls) == 1
    assert json.loads(status_calls[0].args[1]) == {"status": "offline"}
    fake_client.disconnect.assert_called_once()


def test_run_forever_logs_startup_success(caplog):
    # OPS-04: a healthy poller announces itself in `podman logs` -- site,
    # poll interval and broker -- so it's distinguishable from a hung one.
    fake_client = MagicMock()
    config = _make_config()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", return_value={}),
        patch.object(poller, "query_devices", return_value=[]),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle"),
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
        caplog.at_level("INFO", logger=poller._logger.name),
    ):
        result = poller.run_forever(config)

    assert result == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Poller started" in message
        and str(config.cmk_site_id) in message
        and str(config.poll_interval_seconds) in message
        and str(config.mqtt_host) in message
        and str(config.mqtt_port) in message
        for message in messages
    )


def test_run_forever_services_probe_exhausted_is_non_fatal_and_still_runs_cycle(caplog):
    # Phase 12 OPS-03 asymmetry: unlike the mandatory hosts probe, a
    # permanently-failing services probe must not abort the poller --
    # gauges/services are disabled for this run, but the hosts cycle still
    # runs.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", return_value={}),
        patch.object(poller, "query_devices", return_value=[]),
        patch.object(
            poller,
            "available_service_columns",
            side_effect=poller.LivestatusError("services table unreachable"),
        ) as mock_probe,
        patch.object(poller, "query_services") as mock_query_services,
        patch.object(poller, "run_cycle") as mock_run_cycle,
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
        patch.object(poller.time, "sleep"),
        caplog.at_level("WARNING", logger=poller._logger.name),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    assert mock_probe.call_count == len(poller._STARTUP_RETRY_DELAYS_SECONDS) + 1
    mock_query_services.assert_not_called()
    mock_run_cycle.assert_called_once()
    assert mock_run_cycle.call_args.kwargs["services"] is None
    assert any("Services probe failed" in record.getMessage() for record in caplog.records)


def test_run_forever_rest_failure_reuses_last_known_good_folder_map():
    # A REST hiccup must degrade only the folder field for that cycle
    # (T-10-11/T-10-12): the cycle still runs, and query_devices still
    # receives the previous cycle's folder map rather than an empty one.
    fake_client = MagicMock()
    captured_folders: list[dict] = []

    def _fake_query_devices(host, port, columns, timeout, *, folders=None, host_config=None):
        captured_folders.append(folders)
        return []

    class _TwoShotEvent(_OneShotEvent):
        """Lets run_forever execute exactly two loop iterations."""

        def __init__(self):
            super().__init__()
            self._calls = 0

        def wait(self, timeout=None):
            self._calls += 1
            if self._calls >= 2:
                self._stopped = True
            return False

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(
            poller,
            "fetch_host_config",
            side_effect=[
                {"web1": poller.HostConfigInfo(folder="vlan10")},
                poller.RestError("REST hiccup"),
            ],
        ),
        patch.object(poller, "query_devices", side_effect=_fake_query_devices),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle"),
        patch.object(poller.threading, "Event", return_value=_TwoShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    assert captured_folders == [{"web1": "vlan10"}, {"web1": "vlan10"}]


def test_run_forever_rest_never_succeeded_leaves_folders_empty_and_still_runs_cycle():
    fake_client = MagicMock()
    captured_folders: list[dict] = []

    def _fake_query_devices(host, port, columns, timeout, *, folders=None, host_config=None):
        captured_folders.append(folders)
        return []

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", side_effect=poller.RestError("never up")),
        patch.object(poller, "query_devices", side_effect=_fake_query_devices),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle") as mock_run_cycle,
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    assert captured_folders == [{}]
    mock_run_cycle.assert_called_once()


# Regression (CR-04, Phase 10 code review): `--once` called query_devices without
# `folders=`, so the documented one-shot verification path published retained
# `status` AND `topology` with every folder blank, overwriting correct retained
# values on the broker. `run_forever` passed folders correctly; only this branch
# did not, and nothing covered `--once` at all.
def test_once_branch_enriches_snapshots_with_folder_map(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mqtt_poller.py", "--once"])
    with (
        patch.object(poller.PollerConfig, "from_env", staticmethod(lambda: _make_config())),
        patch.object(poller, "configure_logging"),
        patch.object(poller, "reconcile_state", return_value=poller.PollerState(previous_nodes={}, last_status={}, events=[], since="t")),
        patch.object(poller, "build_mqtt_client"),
        patch.object(poller, "shutdown_mqtt_client"),
        patch.object(poller, "available_host_columns", return_value={"name", "state", "alias"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state", "alias"]),
        patch.object(
            poller, "fetch_host_config", return_value={"192.168.0.1": poller.HostConfigInfo(folder="folder2")}
        ),
        patch.object(poller, "query_devices", return_value=[]) as mock_query,
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle"),
    ):
        assert poller.main() == 0
    assert mock_query.call_args.kwargs["folders"] == {"192.168.0.1": "folder2"}


def test_once_branch_degrades_when_folder_fetch_fails(monkeypatch):
    """A REST failure must not abort the one-shot run -- same posture as run_forever."""
    monkeypatch.setattr(sys, "argv", ["mqtt_poller.py", "--once"])
    with (
        patch.object(poller.PollerConfig, "from_env", staticmethod(lambda: _make_config())),
        patch.object(poller, "configure_logging"),
        patch.object(poller, "reconcile_state", return_value=poller.PollerState(previous_nodes={}, last_status={}, events=[], since="t")),
        patch.object(poller, "build_mqtt_client"),
        patch.object(poller, "shutdown_mqtt_client"),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", side_effect=poller.RestError("401")),
        patch.object(poller, "query_devices", return_value=[]) as mock_query,
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller, "run_cycle"),
    ):
        assert poller.main() == 0
    assert mock_query.call_args.kwargs["folders"] == {}


# --- stale retained-topic sweep (quick 260925-b81) -----------------------------


def _tombstones(mock_client):
    return [c for c in mock_client.publish.call_args_list if c.kwargs.get("payload", "unset") is None]


def _ghost_topics(device_id):
    return {
        f"sites/testsite/lan/devices/{device_id}/status",
        f"sites/testsite/lan/devices/{device_id}/history",
        f"sites/testsite/lan/devices/{device_id}/services",
        f"sites/testsite/lan/devices/{device_id}/service_history",
    }


def test_reconcile_state_collects_retained_ids_from_per_device_topics():
    retained = [
        ("sites/testsite/lan/devices/x/status", b"{}"),
        ("sites/testsite/lan/devices/y/services", b"[]"),
        ("sites/testsite/lan/devices/z/history", b"[]"),
        ("sites/testsite/lan/devices/w/service_history", b"[]"),
        ("sites/testsite/lan/devices/cleared/status", b""),
        (poller.site_topic(poller.TOPIC_TOPOLOGY), b'{"devices": []}'),
    ]

    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.site_topic(poller.TOPIC_TOPOLOGY):
                for msg_topic, payload in retained:
                    mock_client.on_message(mock_client, None, _make_message(msg_topic, payload))

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.retained_ids == {"x", "y"}
    assert state.legacy_retained_topics == {
        "sites/testsite/lan/devices/z/history",
        "sites/testsite/lan/devices/w/service_history",
    }


def test_reconcile_state_subscribes_topology_after_per_device_wildcards():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    topics = [c.args[0] for c in mock_client.subscribe.call_args_list]
    assert topics[-1] == poller.site_topic(poller.TOPIC_TOPOLOGY)
    for suffix in ("status", "history", "services", "service_history"):
        assert f"sites/testsite/lan/devices/+/{suffix}" in topics
    assert "sites/testsite/lan/incidents/+/status" in topics


def test_run_cycle_sweep_clears_stale_ids_and_keeps_live_ones():
    client = MagicMock()
    state = _poller_state()
    state.retained_ids = {"ghost", "live"}

    poller.run_cycle(client, _make_config(), state, [_snapshot("live")], allow_stale_sweep=True)

    tombstones = _tombstones(client)
    assert {c.args[0] for c in tombstones} == _ghost_topics("ghost")
    for call in tombstones:
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1
    assert state.retained_ids == set()


def test_run_cycle_sweep_keeps_every_live_id():
    client = MagicMock()
    state = _poller_state()
    state.retained_ids = {"a", "b"}

    poller.run_cycle(
        client, _make_config(), state, [_snapshot("a"), _snapshot("b")], allow_stale_sweep=True
    )

    assert _tombstones(client) == []


def test_run_cycle_sweep_gate_off_clears_nothing_and_keeps_ids():
    client = MagicMock()
    state = _poller_state()
    state.retained_ids = {"ghost"}

    poller.run_cycle(client, _make_config(), state, [])

    assert _tombstones(client) == []
    assert state.retained_ids == {"ghost"}


def test_run_cycle_sweep_does_not_double_tombstone_previous_nodes():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})
    state.retained_ids = {"a"}

    poller.run_cycle(client, _make_config(), state, [], allow_stale_sweep=True)

    topics = [c.args[0] for c in _tombstones(client)]
    assert sorted(topics) == sorted(_ghost_topics("a"))
    events = json.loads(_published(client, poller.site_topic(poller.TOPIC_EVENTS))[0].args[1])
    assert [e["event"] for e in events if e["device_id"] == "a"] == ["removed"]


def test_run_cycle_sweep_emits_no_removed_event_for_stale_ids():
    client = MagicMock()
    state = _poller_state()
    state.retained_ids = {"ghost"}

    poller.run_cycle(client, _make_config(), state, [_snapshot("live")], allow_stale_sweep=True)

    events = json.loads(_published(client, poller.site_topic(poller.TOPIC_EVENTS))[0].args[1])
    assert all(e["device_id"] != "ghost" for e in events)


def _reconcile_with_messages(messages):
    """Run reconcile_state, delivering `messages` when the topology subscribe is sent."""
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.site_topic(poller.TOPIC_TOPOLOGY):
                for msg in messages:
                    mock_client.on_message(mock_client, None, msg)

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))
    return state, mock_client


def test_reconcile_state_collects_legacy_retained_topics():
    legacy = [
        "lan/devices/x/status",
        "lan/devices/topology",
        "lan/events/recent",
        "lan/poller/status",
        "lan/incidents/inc-a/status",
        "admin/faked",
    ]
    state, _ = _reconcile_with_messages([_make_message(t, b"{}") for t in legacy])
    assert state.legacy_retained_topics == set(legacy)


def test_reconcile_state_ignores_non_retained_or_empty_legacy_messages():
    state, _ = _reconcile_with_messages(
        [
            _make_message("lan/devices/a/status", b"{}", retain=False),
            _make_message("lan/devices/b/status", b""),
            _make_message("admin/cmd", b"{}"),
            _make_message("other/topic", b"{}"),
        ]
    )
    assert state.legacy_retained_topics == set()


def test_reconcile_state_legacy_messages_do_not_touch_site_state():
    state, _ = _reconcile_with_messages(
        [
            _make_message("lan/devices/x/status", b"{}"),
            _make_message("lan/devices/x/history", b"[{}]"),
            _make_message("lan/devices/topology", b'{"devices": [{"id": "x"}]}'),
            _make_message("lan/events/recent", b'[{"a": 1}]'),
            _make_message("lan/incidents/inc-a/status", b"{}"),
        ]
    )
    assert state.retained_ids == set()
    assert state.previous_nodes == {}
    assert state.events == []
    assert state.previous_incidents == {}


def test_reconcile_state_subscribes_legacy_topics_before_topology_never_admin_wildcard():
    _, mock_client = _reconcile_with_messages([])
    topics = [c.args[0] for c in mock_client.subscribe.call_args_list]
    assert topics[-1] == poller.site_topic(poller.TOPIC_TOPOLOGY)
    assert topics.index("lan/#") < len(topics) - 1
    assert topics.index("admin/faked") < len(topics) - 1
    assert "admin/#" not in topics


def test_reconcile_state_admin_faked_prefers_new_namespace_over_legacy():
    state, _ = _reconcile_with_messages(
        [
            _make_message("admin/faked", b'{"hosts": {"old": "DOWN"}}'),
            _make_message(
                poller.site_topic(poller.TOPIC_ADMIN_FAKED), b'{"hosts": {"new": "UP"}}'
            ),
        ]
    )
    assert state.admin_faked == {"new": "UP"}


def test_reconcile_state_admin_faked_seeded_from_legacy_when_new_absent():
    state, _ = _reconcile_with_messages(
        [_make_message("admin/faked", b'{"hosts": {"old": "DOWN"}}')]
    )
    assert state.admin_faked == {"old": "DOWN"}
    assert "admin/faked" in state.legacy_retained_topics


_LEGACY_SET = {"lan/devices/x/status", "lan/devices/topology", "admin/faked"}


def test_run_cycle_sweep_tombstones_legacy_topics_once():
    client = MagicMock()
    state = _poller_state()
    state.legacy_retained_topics = set(_LEGACY_SET)

    poller.run_cycle(client, _make_config(), state, [_snapshot("live")], allow_stale_sweep=True)

    tombstones = _tombstones(client)
    assert [c.args[0] for c in tombstones] == sorted(_LEGACY_SET)
    for call in tombstones:
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1
    assert state.legacy_retained_topics == set()

    client.reset_mock()
    poller.run_cycle(client, _make_config(), state, [_snapshot("live")], allow_stale_sweep=True)
    assert _tombstones(client) == []


def test_run_cycle_sweep_gate_off_keeps_legacy_topics():
    client = MagicMock()
    state = _poller_state()
    state.legacy_retained_topics = set(_LEGACY_SET)

    poller.run_cycle(client, _make_config(), state, [_snapshot("live")])

    assert _tombstones(client) == []
    assert state.legacy_retained_topics == _LEGACY_SET


def test_publish_raw_tombstone_refuses_namespaced_topics(caplog):
    client = MagicMock()
    with caplog.at_level("WARNING"):
        poller.publish_raw_tombstone(client, "sites/testsite/lan/devices/x/status")
        poller.publish_raw_tombstone(client, "sites/othersite/lan/devices/x/history")
    client.publish.assert_not_called()
    assert "Refusing" in caplog.text


def test_publish_raw_tombstone_accepts_this_sites_retired_history_topic():
    client = MagicMock()
    poller.publish_raw_tombstone(client, "sites/testsite/lan/devices/x/history")
    assert client.publish.call_args.args[0] == "sites/testsite/lan/devices/x/history"
    assert client.publish.call_args.kwargs["payload"] is None


def test_reconcile_collects_retained_history_topics_and_sweep_clears_them_once():
    history = "sites/testsite/lan/devices/web1/history"
    service_history = "sites/testsite/lan/devices/web1/service_history"
    state, _ = _reconcile_with_messages(
        [
            _make_message(history, b"[{}]"),
            _make_message(service_history, b"[{}]"),
            _make_message("sites/testsite/lan/devices/a/history", b""),
            _make_message("sites/testsite/lan/devices/b/history", b"[{}]", retain=False),
        ]
    )
    assert state.legacy_retained_topics == {history, service_history}

    client = MagicMock()
    poller.run_cycle(client, _make_config(), state, [_snapshot("web1")], allow_stale_sweep=False)
    assert _tombstones(client) == []
    assert state.legacy_retained_topics == {history, service_history}

    client.reset_mock()
    poller.run_cycle(client, _make_config(), state, [_snapshot("web1")], allow_stale_sweep=True)
    assert {c.args[0] for c in _tombstones(client)} == {history, service_history}
    assert state.legacy_retained_topics == set()


def test_legacy_sweep_emits_no_event_and_no_sites_tombstone():
    client = MagicMock()
    state = _poller_state()
    state.legacy_retained_topics = set(_LEGACY_SET)

    poller.run_cycle(client, _make_config(), state, [_snapshot("live")], allow_stale_sweep=True)

    assert all(not c.args[0].startswith("sites/") for c in _tombstones(client))
    events = json.loads(_published(client, poller.site_topic(poller.TOPIC_EVENTS))[0].args[1])
    assert all(e["device_id"] != "x" for e in events)


def _run_forever_one_cycle(*, patch_run_cycle, state=None, rest=None, devices=None):
    """Run `run_forever` for exactly one cycle; `rest`/`devices` are patch kwargs."""
    fake_client = MagicMock()
    with (
        patch.object(poller, "reconcile_state", return_value=state or _poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_config", **(rest or {"return_value": {}})),
        patch.object(poller, "query_devices", **(devices or {"return_value": []})),
        patch.object(
            poller, "available_service_columns", return_value={"host_name", "description", "state"}
        ),
        patch.object(poller, "query_services", return_value=[]),
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        if patch_run_cycle:
            with patch.object(poller, "run_cycle") as mock_run_cycle:
                poller.run_forever(_make_config())
            return fake_client, mock_run_cycle
        poller.run_forever(_make_config())
        return fake_client, None


def test_run_forever_failed_livestatus_query_clears_nothing():
    state = _poller_state()
    state.retained_ids = {"ghost"}

    client, _ = _run_forever_one_cycle(
        patch_run_cycle=False,
        state=state,
        devices={"side_effect": poller.LivestatusError("boom")},
    )

    assert _tombstones(client) == []
    assert state.retained_ids == {"ghost"}


def test_run_forever_sweep_gate_rest_confirms_empty_site():
    _, mock_run_cycle = _run_forever_one_cycle(patch_run_cycle=True)
    assert mock_run_cycle.call_args.kwargs["allow_stale_sweep"] is True


def test_run_forever_sweep_gate_off_when_rest_failed_and_livestatus_empty():
    _, mock_run_cycle = _run_forever_one_cycle(
        patch_run_cycle=True, rest={"side_effect": poller.RestError("boom")}
    )
    assert mock_run_cycle.call_args.kwargs["allow_stale_sweep"] is False


def test_run_forever_sweep_gate_off_when_rest_reports_hosts_but_livestatus_empty():
    host_config = {"h1": poller.HostConfigInfo()}
    _, mock_run_cycle = _run_forever_one_cycle(
        patch_run_cycle=True, rest={"return_value": host_config}
    )
    assert mock_run_cycle.call_args.kwargs["allow_stale_sweep"] is False


def test_run_forever_sweep_gate_on_when_livestatus_returns_hosts_even_if_rest_failed():
    _, mock_run_cycle = _run_forever_one_cycle(
        patch_run_cycle=True,
        rest={"side_effect": poller.RestError("boom")},
        devices={"return_value": [_snapshot("a")]},
    )
    assert mock_run_cycle.call_args.kwargs["allow_stale_sweep"] is True


# --- RollupScheduler / maybe_run_rollups (Phase 14.1, D-49/D-51/D-52) --------


def test_rollup_scheduler_fresh_instance_is_due_immediately_regardless_of_time():
    scheduler = poller.RollupScheduler()
    now_local = datetime.datetime(2026, 9, 28, 13, 0, tzinfo=datetime.UTC)
    assert scheduler.due(now_local, now_monotonic=0.0) is True
    assert scheduler.due(now_local, now_monotonic=99999.0) is True


def test_rollup_scheduler_not_due_again_same_day_after_success():
    scheduler = poller.RollupScheduler()
    scheduler.mark_success(datetime.date(2026, 9, 28))
    for hour in (0, 12, 23):
        now_local = datetime.datetime(2026, 9, 28, hour, 0, tzinfo=datetime.UTC)
        assert scheduler.due(now_local, now_monotonic=0.0) is False


def test_rollup_scheduler_due_after_midnight_delay_on_the_next_day():
    scheduler = poller.RollupScheduler(delay_minutes=5)
    scheduler.mark_success(datetime.date(2026, 9, 28))
    before_delay = datetime.datetime(2026, 9, 29, 0, 3, tzinfo=datetime.UTC)
    after_delay = datetime.datetime(2026, 9, 29, 0, 5, tzinfo=datetime.UTC)
    assert scheduler.due(before_delay, now_monotonic=0.0) is False
    assert scheduler.due(after_delay, now_monotonic=0.0) is True


def test_rollup_scheduler_mark_failure_backs_off_then_retries():
    scheduler = poller.RollupScheduler()
    scheduler.mark_failure(now_monotonic=1000.0)
    now_local = datetime.datetime(2026, 9, 28, 13, 0, tzinfo=datetime.UTC)
    assert scheduler.due(now_local, now_monotonic=1200.0) is False
    assert scheduler.due(now_local, now_monotonic=1300.0) is True


def test_maybe_run_rollups_noop_when_clickhouse_url_unset():
    config = _make_config(clickhouse_url="", s3_endpoint="http://minio:9000")
    scheduler = poller.RollupScheduler()
    s3_holder: dict = {}
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "build_s3_client") as mock_build,
        patch.object(poller, "run_rollups") as mock_run,
    ):
        poller.maybe_run_rollups(
            config, scheduler, s3_holder, tz, datetime.datetime.now(tz), poller.time.monotonic()
        )
    mock_build.assert_not_called()
    mock_run.assert_not_called()
    assert s3_holder == {}


def test_maybe_run_rollups_noop_when_s3_endpoint_unset():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="")
    scheduler = poller.RollupScheduler()
    s3_holder: dict = {}
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    with (
        patch.object(poller, "build_s3_client") as mock_build,
        patch.object(poller, "run_rollups") as mock_run,
    ):
        poller.maybe_run_rollups(
            config, scheduler, s3_holder, tz, datetime.datetime.now(tz), poller.time.monotonic()
        )
    mock_build.assert_not_called()
    mock_run.assert_not_called()


def test_maybe_run_rollups_marks_success_when_zero_failures():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = poller.RollupScheduler()
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        patch.object(poller, "build_s3_client", return_value=MagicMock()),
        patch.object(poller, "run_rollups", return_value=([], 0)),
    ):
        poller.maybe_run_rollups(config, scheduler, {}, tz, now_local, poller.time.monotonic())
    assert scheduler.last_completed_local_date == now_local.date()


def test_maybe_run_rollups_marks_failure_when_run_rollups_reports_failures():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = poller.RollupScheduler()
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        patch.object(poller, "build_s3_client", return_value=MagicMock()),
        patch.object(poller, "run_rollups", return_value=([], 2)),
    ):
        poller.maybe_run_rollups(config, scheduler, {}, tz, now_local, poller.time.monotonic())
    assert scheduler.last_completed_local_date is None
    assert scheduler.next_attempt_monotonic > 0.0


def test_maybe_run_rollups_logs_and_marks_failure_instead_of_raising(caplog):
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = poller.RollupScheduler()
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    with (
        caplog.at_level("WARNING", logger=poller._logger.name),
        patch.object(poller, "build_s3_client", return_value=MagicMock()),
        patch.object(poller, "run_rollups", side_effect=poller.ClickHouseError("boom")),
    ):
        poller.maybe_run_rollups(config, scheduler, {}, tz, now_local, poller.time.monotonic())
    assert scheduler.last_completed_local_date is None
    assert scheduler.next_attempt_monotonic > 0.0
    assert any("Availability rollup run failed" in record.getMessage() for record in caplog.records)


def test_maybe_run_rollups_reuses_s3_client_across_calls():
    config = _make_config(clickhouse_url="http://clickhouse:8123", s3_endpoint="http://minio:9000")
    scheduler = poller.RollupScheduler()
    tz = poller.zoneinfo.ZoneInfo("Asia/Singapore")
    now_local = datetime.datetime.now(tz)
    s3_holder: dict = {}
    with (
        patch.object(poller, "build_s3_client", return_value=MagicMock()) as mock_build,
        patch.object(poller, "run_rollups", return_value=([], 0)),
    ):
        poller.maybe_run_rollups(config, scheduler, s3_holder, tz, now_local, poller.time.monotonic())
        scheduler.next_attempt_monotonic = 0.0
        scheduler.last_completed_local_date = None
        poller.maybe_run_rollups(config, scheduler, s3_holder, tz, now_local, poller.time.monotonic())
    mock_build.assert_called_once()


# --- admin command channel: parsing ---------------------------------------------------


def _admin_payload(**overrides):
    data = {"id": "a1", "action": "down", "hosts": ["sw1"]}
    data.update(overrides)
    return json.dumps(data).encode()


def test_parse_admin_command_valid():
    cmd = poller.parse_admin_command(_admin_payload())
    assert cmd == poller.AdminCommand(id="a1", action="down", hosts=["sw1"])


def test_parse_admin_command_bad_json_rejected_without_id():
    with pytest.raises(poller.AdminCommandError) as exc:
        poller.parse_admin_command(b"not json")
    assert exc.value.reason == "malformed command"
    assert exc.value.command_id is None


def test_parse_admin_command_unknown_action_keeps_id():
    with pytest.raises(poller.AdminCommandError) as exc:
        poller.parse_admin_command(_admin_payload(action="reboot"))
    assert exc.value.reason == "unknown action"
    assert exc.value.command_id == "a1"


@pytest.mark.parametrize("bad_id", ["a;b", "", "x" * 65, 5, None])
def test_parse_admin_command_bad_id_rejected(bad_id):
    with pytest.raises(poller.AdminCommandError) as exc:
        poller.parse_admin_command(_admin_payload(id=bad_id))
    assert exc.value.command_id is None


@pytest.mark.parametrize(
    "bad_hosts",
    ["sw1", [1], ["a;b"], ["a b"], [], [f"h{i}" for i in range(201)], None],
)
def test_parse_admin_command_bad_hosts_rejected(bad_hosts):
    with pytest.raises(poller.AdminCommandError) as exc:
        poller.parse_admin_command(_admin_payload(hosts=bad_hosts))
    assert exc.value.reason == "invalid host list"
    assert exc.value.command_id == "a1"


def test_parse_admin_command_max_hosts_accepted_and_deduplicated():
    cmd = poller.parse_admin_command(_admin_payload(hosts=[f"h{i}" for i in range(200)]))
    assert len(cmd.hosts) == 200
    cmd = poller.parse_admin_command(_admin_payload(hosts=["b", "a", "b"]))
    assert cmd.hosts == ["b", "a"]


def test_parse_admin_command_restore_all_accepts_missing_or_empty_hosts():
    for payload in (
        json.dumps({"id": "r", "action": "restore_all"}).encode(),
        json.dumps({"id": "r", "action": "restore_all", "hosts": []}).encode(),
    ):
        assert poller.parse_admin_command(payload).hosts == []


# --- admin command channel: cascade planner -------------------------------------------


def _ops(actions):
    return {a.host: (a.op, a.cascaded) for a in actions}


def _chain():
    return [
        _snapshot("r1"),
        _snapshot("s1", parents=["r1"]),
        _snapshot("h1", parents=["s1"]),
    ]


def test_plan_admin_actions_down_cascades_unreach_to_managed_descendants():
    result = poller.plan_admin_actions("down", ["r1"], _chain(), {})
    assert _ops(result) == {
        "r1": ("down", False),
        "s1": ("unreach", True),
        "h1": ("unreach", True),
    }


def test_plan_admin_actions_down_cascade_stops_at_unmanaged_switch():
    snaps = [
        _snapshot("r1"),
        _snapshot("um1", parents=["r1"], unmanaged=True),
        _snapshot("gc1", parents=["um1"]),
        _snapshot("gc2", parents=["um1"]),
    ]
    result = poller.plan_admin_actions("down", ["r1"], snaps, {})
    assert _ops(result) == {"r1": ("down", False), "um1": ("unreach", True)}


def test_plan_admin_actions_down_on_unmanaged_host_does_not_cascade():
    snaps = [
        _snapshot("um1", unmanaged=True),
        _snapshot("gc1", parents=["um1"]),
    ]
    result = poller.plan_admin_actions("down", ["um1"], snaps, {})
    assert _ops(result) == {"um1": ("down", False)}


def test_plan_admin_actions_explicit_selection_wins_over_cascade():
    result = poller.plan_admin_actions("down", ["r1", "h1"], _chain(), {})
    ops = _ops(result)
    assert ops["h1"] == ("down", False)
    assert ops["s1"] == ("unreach", True)
    assert len(result) == 3


def test_plan_admin_actions_parents_cycle_terminates():
    snaps = [_snapshot("a", parents=["b"]), _snapshot("b", parents=["a"])]
    result = poller.plan_admin_actions("down", ["a"], snaps, {})
    hosts = [r.host for r in result]
    assert sorted(hosts) == ["a", "b"]
    assert len(hosts) == len(set(hosts))
    assert poller.plan_admin_actions("up", ["a"], snaps, {"a": "DOWN", "b": "UNREACH"})


def test_plan_admin_actions_up_reverses_cascade():
    faked = {"r1": "DOWN", "s1": "UNREACH", "h1": "UNREACH"}
    result = poller.plan_admin_actions("up", ["r1"], _chain(), faked)
    assert _ops(result) == {
        "r1": ("up", False),
        "s1": ("restore", True),
        "h1": ("restore", True),
    }


def test_plan_admin_actions_reverse_cascade_keeps_host_under_other_down_parent():
    snaps = [
        _snapshot("r1"),
        _snapshot("r2"),
        _snapshot("h1", parents=["r1", "r2"]),
    ]
    faked = {"r1": "DOWN", "r2": "DOWN", "h1": "UNREACH"}
    result = poller.plan_admin_actions("up", ["r1"], snaps, faked)
    assert _ops(result) == {"r1": ("up", False)}


def test_plan_admin_actions_restore_all_restores_every_faked_host():
    snaps = [_snapshot("b"), _snapshot("a"), _snapshot("c")]
    result = poller.plan_admin_actions(
        "restore_all", [], snaps, {"b": "UP", "a": "DOWN", "gone": "DOWN"}
    )
    assert [(r.host, r.op, r.cascaded) for r in result] == [
        ("a", "restore", False),
        ("b", "restore", False),
    ]


def test_plan_admin_actions_ignores_unknown_host_ids():
    result = poller.plan_admin_actions("down", ["nope", "h1"], _chain(), {})
    assert _ops(result) == {"h1": ("down", False)}


# --- D-03: inferred switch card with faked children -----------------------------------


def test_compute_incidents_faked_down_children_behind_unmanaged_switch_give_inferred_card():
    # D-03: demo flow fakes two children DOWN behind an unmanaged switch; the existing
    # inferred-switch rule must produce one combined card with no new engine rule.
    snapshots = [
        _snapshot("um1", host_state_raw="UP", unmanaged=True),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
        _snapshot("gc2", host_state_raw="DOWN", parents=["um1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    assert incidents[0]["inferred"] is True
    assert incidents[0]["root"] == "um1"
    assert incidents[0]["not_observable"] == ["gc1", "gc2"]


def test_compute_incidents_single_faked_down_child_stays_plain_root():
    # D-03: one faked child must not blame the switch.
    snapshots = [
        _snapshot("um1", host_state_raw="UP", unmanaged=True),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
        _snapshot("gc2", host_state_raw="UP", parents=["um1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    assert len(incidents) == 1
    assert incidents[0]["root"] == "gc1"
    assert incidents[0]["inferred"] is False


def test_compute_incidents_faked_managed_parent_down_above_unmanaged_switch_keeps_children_listed():
    # D-03: a faked managed DOWN above the switch (switch UNREACH by cascade, children
    # faked DOWN) must still list both children in the combined card.
    snapshots = [
        _snapshot("r1", host_state_raw="DOWN"),
        _snapshot("um1", host_state_raw="UNREACH", unmanaged=True, parents=["r1"]),
        _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
        _snapshot("gc2", host_state_raw="DOWN", parents=["um1"]),
    ]
    incidents = poller.compute_incidents(snapshots)
    listed = set()
    for inc in incidents:
        listed.update(inc["confirmed_down"])
        listed.update(inc["not_observable"])
    assert {"gc1", "gc2"} <= listed


# --- admin command channel: Livestatus builder and sender -----------------------------


def test_build_admin_commands_down():
    cmds = poller.build_admin_commands(poller.AdminAction("h1", "down", False), "10.0.0.5")
    assert cmds == [
        "DISABLE_HOST_CHECK;h1",
        "DISABLE_SVC_CHECK;h1;PING",
        "PROCESS_HOST_CHECK_RESULT;h1;1;CRITICAL - 10.0.0.5: rta nan, lost 100%",
        "PROCESS_SERVICE_CHECK_RESULT;h1;PING;2;CRITICAL - 10.0.0.5: rta nan, lost 100%",
    ]


def test_build_admin_commands_unreach():
    cmds = poller.build_admin_commands(poller.AdminAction("h1", "unreach", True), "10.0.0.5")
    assert cmds[2] == "PROCESS_HOST_CHECK_RESULT;h1;2;CRITICAL - 10.0.0.5: rta nan, lost 100%"
    assert cmds[3] == "PROCESS_SERVICE_CHECK_RESULT;h1;PING;2;CRITICAL - 10.0.0.5: rta nan, lost 100%"


def test_build_admin_commands_up_text_and_rta_range():
    import re

    for _ in range(20):
        cmds = poller.build_admin_commands(poller.AdminAction("h1", "up", False), "10.0.0.5")
        assert cmds[:2] == ["DISABLE_HOST_CHECK;h1", "DISABLE_SVC_CHECK;h1;PING"]
        host_prefix = "PROCESS_HOST_CHECK_RESULT;h1;0;"
        svc_prefix = "PROCESS_SERVICE_CHECK_RESULT;h1;PING;0;"
        assert cmds[2].startswith(host_prefix) and cmds[3].startswith(svc_prefix)
        text = cmds[2][len(host_prefix):]
        assert re.match(r"^OK - 10\.0\.0\.5 rta \d+\.\d{3}ms lost 0%$", text)
        assert 0.2 <= float(text.split("rta ")[1].split("ms")[0]) <= 3.0


def test_build_admin_commands_restore_is_demo_baseline():
    # UAT gap 3: ENABLE_SVC_CHECK made Checkmk really ping a demo host's fake IP (CRITICAL).
    import re

    for _ in range(20):
        cmds = poller.build_admin_commands(poller.AdminAction("h1", "restore", False), "10.0.0.5")
        assert len(cmds) == 3
        assert cmds[0] == "ENABLE_HOST_CHECK;h1"
        host_prefix = "PROCESS_HOST_CHECK_RESULT;h1;0;"
        svc_prefix = "PROCESS_SERVICE_CHECK_RESULT;h1;PING;0;"
        assert cmds[1].startswith(host_prefix) and cmds[2].startswith(svc_prefix)
        text = cmds[1][len(host_prefix):]
        assert text == cmds[2][len(svc_prefix):]
        assert re.match(r"^OK - 10\.0\.0\.5 rta \d+\.\d{3}ms lost 0%$", text)
        assert 0.2 <= float(text.split("rta ")[1].split("ms")[0]) <= 3.0
        for cmd in cmds:
            for forbidden in ("ENABLE_SVC_CHECK", "DISABLE_", "SCHEDULE_", "FORCED"):
                assert forbidden not in cmd


def test_build_admin_commands_restore_unsafe_address_falls_back_to_host_id():
    cmds = poller.build_admin_commands(poller.AdminAction("h1", "restore", False), "a;b")
    assert cmds[1].startswith("PROCESS_HOST_CHECK_RESULT;h1;0;OK - h1 rta ")


def test_build_admin_keepalive_commands_states():
    up = poller.build_admin_keepalive_commands("h1", "UP", "10.0.0.5")
    assert up[0].startswith("PROCESS_HOST_CHECK_RESULT;h1;0;OK - 10.0.0.5 rta ")
    assert up[1].startswith("PROCESS_SERVICE_CHECK_RESULT;h1;PING;0;OK - 10.0.0.5 rta ")
    down = poller.build_admin_keepalive_commands("h1", "DOWN", "10.0.0.5")
    assert down == [
        "PROCESS_HOST_CHECK_RESULT;h1;1;CRITICAL - 10.0.0.5: rta nan, lost 100%",
        "PROCESS_SERVICE_CHECK_RESULT;h1;PING;2;CRITICAL - 10.0.0.5: rta nan, lost 100%",
    ]
    unreach = poller.build_admin_keepalive_commands("h1", "UNREACH", "10.0.0.5")
    assert unreach[0].startswith("PROCESS_HOST_CHECK_RESULT;h1;2;")
    for cmd in up + down + unreach:
        assert not cmd.startswith(("DISABLE_", "ENABLE_"))


def test_build_admin_keepalive_commands_rejects_bad_input():
    with pytest.raises(ValueError):
        poller.build_admin_keepalive_commands("h1", "RESTORED", "10.0.0.5")
    with pytest.raises(ValueError):
        poller.build_admin_keepalive_commands("h;1", "UP", "10.0.0.5")


@pytest.mark.parametrize("bad", ["a;b", "x'y", "1.2.3.4 5", "a\nb", "a\rb", ""])
def test_build_admin_commands_unsafe_address_falls_back_to_host_id(bad):
    cmds = poller.build_admin_commands(poller.AdminAction("h1", "down", False), bad)
    assert cmds[2] == "PROCESS_HOST_CHECK_RESULT;h1;1;CRITICAL - h1: rta nan, lost 100%"
    for cmd in cmds:
        assert "\n" not in cmd and "\r" not in cmd and "'" not in cmd
        if cmd.startswith("PROCESS_HOST"):
            assert ";" not in cmd.split(";", 3)[3]


def test_build_admin_commands_rejects_bad_host_id():
    with pytest.raises(ValueError):
        poller.build_admin_commands(poller.AdminAction("h;1", "down", False), "10.0.0.5")


def test_send_livestatus_commands_one_connection_per_command():
    socks = [_fake_connection(b""), _fake_connection(b"")]
    with patch("socket.create_connection", side_effect=socks) as create:
        poller.send_livestatus_commands("lh", 6557, ["A;h1", "B;h1"], 5.0)
    assert create.call_count == 2
    sent = [s.sendall.call_args[0][0].decode() for s in socks]
    assert sent[0].startswith("COMMAND [") and sent[0].endswith("] A;h1\n\n")
    assert sent[1].endswith("] B;h1\n\n")
    socks[0].shutdown.assert_called_once()


def test_send_livestatus_commands_rejects_newline_before_sending():
    with patch("socket.create_connection") as create, pytest.raises(ValueError):
        poller.send_livestatus_commands("lh", 6557, ["ok;h1", "bad\nx"], 5.0)
    create.assert_not_called()


@pytest.mark.parametrize("err", [OSError("boom"), TimeoutError("slow")])
def test_send_livestatus_commands_wraps_oserror(err):
    with (
        patch("socket.create_connection", side_effect=err),
        pytest.raises(poller.LivestatusError),
    ):
        poller.send_livestatus_commands("lh", 6557, ["A;h1"], 5.0)


# --- Admin command worker, faked-set derivation and wiring (Phase 16) -------


@pytest.fixture(autouse=True)
def _no_admin_thread_in_run_forever_tests(request):
    # The run_forever tests patch `threading.Event` globally, which breaks `Thread()`
    # construction; the worker thread itself is covered by direct `_run`/`process_one` tests.
    if request.node.name.startswith("test_run_forever"):
        with (
            patch.object(poller.AdminCommandWorker, "start"),
            patch.object(poller.AdminCommandWorker, "stop"),
        ):
            yield
    else:
        yield


def test_query_faked_hosts_requires_host_and_ping_disabled():
    with patch.object(
        poller,
        "_livestatus_request",
        side_effect=[json.dumps([["h1", 1, 0], ["h2", 0, 0]]), json.dumps([["h1", 0], ["h2", 1]])],
    ):
        assert poller.query_faked_hosts("lh", 6557, 5.0) == {"h1": "DOWN"}


def test_query_faked_hosts_counts_host_without_ping_service():
    with patch.object(
        poller,
        "_livestatus_request",
        side_effect=[json.dumps([["um1", 0, 0]]), json.dumps([])],
    ):
        assert poller.query_faked_hosts("lh", 6557, 5.0) == {"um1": "UP"}


def test_query_faked_hosts_empty_body_is_empty():
    with patch.object(poller, "_livestatus_request", side_effect=["", ""]):
        assert poller.query_faked_hosts("lh", 6557, 5.0) == {}


def test_query_faked_hosts_malformed_raises():
    with (
        patch.object(poller, "_livestatus_request", side_effect=["not json", ""]),
        pytest.raises(poller.LivestatusError),
    ):
        poller.query_faked_hosts("lh", 6557, 5.0)


def test_refresh_admin_faked_publishes_only_on_change():
    client = MagicMock()
    context = poller.AdminContext()
    results = [{"h1": "DOWN"}, {"h1": "DOWN"}, {"h1": "DOWN", "h2": "UNREACH"}]
    with patch.object(poller, "query_faked_hosts", side_effect=results):
        for _ in results:
            poller.refresh_admin_faked(client, context, _make_config())

    calls = _published(client, poller.site_topic(poller.TOPIC_ADMIN_FAKED))
    assert len(calls) == 2
    assert calls[0].kwargs["qos"] == 1 and calls[0].kwargs["retain"] is True
    payload = json.loads(calls[0].args[1])
    assert payload["hosts"] == {"h1": "DOWN"}
    assert payload["source"] == "livestatus"
    assert "timestamp" in payload


def test_refresh_admin_faked_swallows_livestatus_error():
    client = MagicMock()
    context = poller.AdminContext()
    with patch.object(poller, "query_faked_hosts", side_effect=poller.LivestatusError("x")):
        poller.refresh_admin_faked(client, context, _make_config())

    client.publish.assert_not_called()


def test_admin_context_ledger_apply_and_prune():
    client = MagicMock()
    context = poller.AdminContext()
    context.use_ledger = True
    context.apply_ledger(
        [poller.AdminAction("a", "down", False), poller.AdminAction("b", "unreach", True)]
    )
    context.apply_ledger([poller.AdminAction("a", "restore", False)])
    assert context.faked() == {"b": "UNREACH"}

    poller.refresh_admin_faked(client, context, _make_config())
    payload = json.loads(_published(client, poller.site_topic(poller.TOPIC_ADMIN_FAKED))[0].args[1])
    assert payload["source"] == "ledger"
    assert payload["hosts"] == {"b": "UNREACH"}

    context.update_snapshots([_snapshot("z")])
    poller.refresh_admin_faked(client, context, _make_config())
    assert context.faked() == {}


def test_publish_admin_ack_not_retained():
    client = MagicMock()
    poller.publish_admin_ack(client, {"id": "x"})
    args, kwargs = client.publish.call_args
    assert args[0] == poller.site_topic(poller.TOPIC_ADMIN_ACK)
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is False


def _reconcile_with_admin_faked(payload: bytes):
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.site_topic(poller.TOPIC_ADMIN_FAKED):
                mock_client.on_message(
                    mock_client, None, _make_message(poller.site_topic(poller.TOPIC_ADMIN_FAKED), payload)
                )

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))
    return state, mock_client


def test_reconcile_state_seeds_admin_faked_from_retained_topic():
    state, _ = _reconcile_with_admin_faked(b'{"hosts": {"h1": "DOWN"}}')
    assert state.admin_faked == {"h1": "DOWN"}


def test_reconcile_state_ignores_malformed_admin_faked():
    state, _ = _reconcile_with_admin_faked(b"not json")
    assert state.admin_faked == {}
    state, _ = _reconcile_with_admin_faked(
        b'{"hosts": {"h1": "BOGUS", "bad id!": "DOWN", "ok": "UP"}}'
    )
    assert state.admin_faked == {"ok": "UP"}


def test_reconcile_state_subscribes_topology_after_admin_faked():
    _, mock_client = _reconcile_with_admin_faked(b"{}")
    topics = [c.args[0] for c in mock_client.subscribe.call_args_list]
    assert topics.index(poller.site_topic(poller.TOPIC_ADMIN_FAKED)) < topics.index(poller.site_topic(poller.TOPIC_TOPOLOGY))
    assert topics[-1] == poller.site_topic(poller.TOPIC_TOPOLOGY)


def _admin_worker(snapshots=None, **kwargs):
    context = poller.AdminContext()
    if snapshots is not None:
        context.update_snapshots(snapshots)
    kwargs.setdefault("send_fn", MagicMock())
    kwargs.setdefault("sleep_fn", MagicMock())
    kwargs.setdefault("refresh_fn", MagicMock())
    worker = poller.AdminCommandWorker(_make_config(), context, **kwargs)
    client = MagicMock()
    worker.attach_client(client)
    return worker, client, context


def _cmd(id_="c1", action="down", hosts=("h1",)):
    return json.dumps({"id": id_, "action": action, "hosts": list(hosts)}).encode()


def _acks(client):
    return [json.loads(c.args[1]) for c in _published(client, poller.site_topic(poller.TOPIC_ADMIN_ACK))]


def test_admin_worker_drops_retained_command():
    worker, client, _ = _admin_worker([_snapshot("h1")])
    worker.submit(_cmd(), retained=True)
    assert worker._queue.empty()
    client.publish.assert_not_called()


def test_admin_worker_acks_unknown_action():
    worker, client, _ = _admin_worker([_snapshot("h1")])
    worker.submit(_cmd(action="reboot"), retained=False)
    acks = _acks(client)
    assert len(acks) == 1
    assert acks[0]["ok"] is False and acks[0]["detail"] == "unknown action"


def test_admin_worker_drops_payload_without_id():
    worker, client, _ = _admin_worker([_snapshot("h1")])
    worker.submit(b'{"action": "down"}', retained=False)
    worker.submit(b"garbage", retained=False)
    client.publish.assert_not_called()


def test_admin_worker_acks_busy_when_queue_full():
    worker, client, _ = _admin_worker([_snapshot("h1")])
    for i in range(poller.ADMIN_QUEUE_MAX):
        worker.submit(_cmd(id_=f"c{i}"), retained=False)
    client.publish.assert_not_called()
    worker.submit(_cmd(id_="overflow"), retained=False)
    acks = _acks(client)
    assert acks[0]["ok"] is False and acks[0]["detail"] == "poller busy, try again"


def test_admin_worker_dedupes_command_ids():
    worker, _, _ = _admin_worker([_snapshot("h1")])
    worker.submit(_cmd(id_="same"), retained=False)
    worker.submit(_cmd(id_="same"), retained=False)
    assert worker._queue.qsize() == 1


def test_admin_worker_no_host_list_yet():
    worker, _, _ = _admin_worker()
    ack = worker.process_one(poller.parse_admin_command(_cmd()))
    assert ack["ok"] is False and ack["detail"] == "poller has no host list yet"


def test_admin_worker_skips_unknown_hosts():
    send = MagicMock()
    worker, _, _ = _admin_worker([_snapshot("h1")], send_fn=send)
    ack = worker.process_one(poller.parse_admin_command(_cmd(hosts=("h1", "ghost"))))
    assert ack["ok"] is True
    assert ack["skipped"] == ["ghost"]
    sent = send.call_args.args[2]
    assert all("ghost" not in c for c in sent) and any("h1" in c for c in sent)


def test_admin_worker_all_hosts_unknown_fails():
    worker, _, _ = _admin_worker([_snapshot("h1")])
    ack = worker.process_one(poller.parse_admin_command(_cmd(hosts=("ghost",))))
    assert ack["ok"] is False and ack["detail"] == "no known hosts in command"


def test_admin_worker_retries_then_fails():
    send = MagicMock(side_effect=poller.LivestatusError("down"))
    sleep = MagicMock()
    worker, _, _ = _admin_worker([_snapshot("h1")], send_fn=send, sleep_fn=sleep)
    ack = worker.process_one(poller.parse_admin_command(_cmd()))
    assert ack["ok"] is False
    assert ack["detail"].startswith("Livestatus unreachable:")
    assert [c.args[0] for c in sleep.call_args_list] == [3, 5, 10]
    assert send.call_count == 4


def test_admin_worker_retry_then_success():
    send = MagicMock(side_effect=[poller.LivestatusError("down"), None])
    worker, _, _ = _admin_worker([_snapshot("h1")], send_fn=send)
    ack = worker.process_one(poller.parse_admin_command(_cmd()))
    assert ack["ok"] is True
    assert ack["detail"].startswith("sent ")


def test_admin_worker_down_cascade_ack_shape():
    refresh = MagicMock()
    worker, _, _ = _admin_worker(
        [_snapshot("p"), _snapshot("c", parents=["p"])], refresh_fn=refresh
    )
    ack = worker.process_one(poller.parse_admin_command(_cmd(hosts=("p",))))
    assert ack["ok"] is True and ack["action"] == "down"
    assert ack["applied"] == [
        {"host": "p", "state": "DOWN", "cascaded": False},
        {"host": "c", "state": "UNREACH", "cascaded": True},
    ]
    refresh.assert_called_once()


def test_admin_worker_restore_all_nothing_to_do():
    send = MagicMock()
    worker, _, _ = _admin_worker([_snapshot("h1")], send_fn=send)
    ack = worker.process_one(poller.parse_admin_command(_cmd(action="restore_all", hosts=())))
    assert ack["ok"] is True and ack["detail"] == "nothing to do"
    send.assert_not_called()


def test_admin_worker_internal_error_acks_and_continues():
    worker, client, _ = _admin_worker([_snapshot("h1")])
    command = poller.parse_admin_command(_cmd())
    with patch.object(worker, "process_one", side_effect=RuntimeError("boom")):
        worker._handle(command)
    acks = _acks(client)
    assert acks[0]["ok"] is False and acks[0]["detail"] == "internal error"
    # The worker still processes a later command normally.
    worker._handle(poller.parse_admin_command(_cmd(id_="c2")))
    assert _acks(client)[1]["ok"] is True


def test_admin_worker_ledger_mode_records_actions():
    worker, _, context = _admin_worker([_snapshot("h1")])
    context.use_ledger = True
    worker.process_one(poller.parse_admin_command(_cmd()))
    assert context.faked() == {"h1": "DOWN"}


def test_build_mqtt_client_subscribes_admin_cmd_on_connect():
    worker, _, _ = _admin_worker()
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config(), admin_worker=worker)
        mock_client.on_connect(mock_client, None, {}, 0, None)

    mock_client.subscribe.assert_called_once_with(poller.site_topic(poller.TOPIC_ADMIN_CMD), qos=1)


def test_build_mqtt_client_routes_admin_cmd_to_worker():
    worker = MagicMock()
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config(), admin_worker=worker)
        msg = SimpleNamespace(topic=poller.site_topic(poller.TOPIC_ADMIN_CMD), payload=b"x", retain=False)
        mock_client.on_message(mock_client, None, msg)
        mock_client.on_message(
            mock_client, None, SimpleNamespace(topic="other", payload=b"y", retain=False)
        )

    worker.submit.assert_called_once_with(b"x", False)


def test_build_mqtt_client_without_worker_does_not_subscribe_admin():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config())
        mock_client.on_connect(mock_client, None, {}, 0, None)

    mock_client.subscribe.assert_not_called()


# --- restore baseline through the worker, faked derivation, keepalive ------------------


def _sent_commands(send_fn):
    return [c for call in send_fn.call_args_list for c in call.args[2]]


def test_worker_reverse_cascade_restore_never_enables_ping_check():
    # UAT gap 3b: Set UP on a managed parent restores the faked-UNREACH child.
    snaps = [_snapshot("p"), _snapshot("c", parents=["p"])]
    worker, _, context = _admin_worker(snaps)
    context.set_faked({"p": "DOWN", "c": "UNREACH"})
    worker.process_one(poller.parse_admin_command(_cmd(action="up", hosts=("p",))))
    cmds = _sent_commands(worker._send_fn)
    assert "ENABLE_HOST_CHECK;c" in cmds
    assert any(c.startswith("PROCESS_SERVICE_CHECK_RESULT;c;PING;0;") for c in cmds)
    assert not any("ENABLE_SVC_CHECK" in c for c in cmds)


def test_worker_restore_all_never_enables_ping_check():
    worker, _, context = _admin_worker([_snapshot("h1")])
    context.set_faked({"h1": "DOWN"})
    worker.process_one(poller.parse_admin_command(_cmd(action="restore_all", hosts=())))
    cmds = _sent_commands(worker._send_fn)
    assert "ENABLE_HOST_CHECK;h1" in cmds
    assert not any("ENABLE_SVC_CHECK" in c for c in cmds)


def test_query_faked_hosts_ignores_host_with_enabled_host_check():
    with patch.object(
        poller,
        "_livestatus_request",
        side_effect=[json.dumps([["h1", 1, 1]]), json.dumps([["h1", 0]])],
    ):
        assert poller.query_faked_hosts("lh", 6557, 5.0) == {}


def test_query_faked_hosts_restored_baseline_shape_is_not_faked():
    with patch.object(
        poller,
        "_livestatus_request",
        side_effect=[json.dumps([]), json.dumps([["h1", 0]])],
    ):
        assert poller.query_faked_hosts("lh", 6557, 5.0) == {}


def test_ledger_restore_pops_host():
    context = poller.AdminContext()
    context.use_ledger = True
    context.set_faked({"a": "DOWN"})
    context.apply_ledger([poller.AdminAction("a", "restore", False)])
    assert context.faked() == {}


def test_keepalive_interval_constant():
    assert poller.ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS == 30
    assert poller.ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS <= 60


def test_keepalive_fake_clock_cadence():
    query = MagicMock(return_value={"h1": "DOWN"})
    worker, _, context = _admin_worker([_snapshot("h1")], query_fn=query)
    context.set_faked({"h1": "DOWN"})
    worker.maybe_keepalive(0.0)
    assert worker._send_fn.call_count == 1
    cmds = worker._send_fn.call_args.args[2]
    assert [c.split(";")[0] for c in cmds] == [
        "PROCESS_HOST_CHECK_RESULT",
        "PROCESS_SERVICE_CHECK_RESULT",
    ]
    worker.maybe_keepalive(29.0)
    assert worker._send_fn.call_count == 1
    worker.maybe_keepalive(30.0)
    assert worker._send_fn.call_count == 2
    worker._sleep_fn.assert_not_called()


def test_keepalive_no_io_when_nothing_faked():
    query = MagicMock()
    worker, _, _ = _admin_worker([_snapshot("h1")], query_fn=query)
    worker.maybe_keepalive(0.0)
    query.assert_not_called()
    worker._send_fn.assert_not_called()


def test_keepalive_only_refreshes_faked_known_hosts():
    query = MagicMock(return_value={"h1": "UP", "ghost": "DOWN"})
    worker, _, context = _admin_worker([_snapshot("h1"), _snapshot("h2")], query_fn=query)
    context.set_faked({"h1": "UP", "ghost": "DOWN"})
    worker.maybe_keepalive(0.0)
    cmds = _sent_commands(worker._send_fn)
    assert cmds and all(";h1;" in c for c in cmds)


def test_keepalive_requeries_and_skips_host_restored_meanwhile():
    query = MagicMock(return_value={})
    worker, _, context = _admin_worker([_snapshot("h1")], query_fn=query)
    context.set_faked({"h1": "DOWN"})
    worker.maybe_keepalive(0.0)
    query.assert_called_once()
    worker._send_fn.assert_not_called()


def test_keepalive_ledger_mode_uses_context_and_never_queries():
    query = MagicMock()
    worker, _, context = _admin_worker([_snapshot("h1")], query_fn=query)
    context.use_ledger = True
    context.set_faked({"h1": "UNREACH"})
    worker.maybe_keepalive(0.0)
    query.assert_not_called()
    assert worker._send_fn.call_count == 1


def test_keepalive_query_failure_sends_nothing_and_does_not_raise():
    query = MagicMock(side_effect=poller.LivestatusError("boom"))
    worker, _, context = _admin_worker([_snapshot("h1")], query_fn=query)
    context.set_faked({"h1": "DOWN"})
    worker.maybe_keepalive(0.0)
    worker._send_fn.assert_not_called()


def test_keepalive_send_failure_does_not_raise_or_retry():
    send = MagicMock(side_effect=poller.LivestatusError("boom"))
    query = MagicMock(return_value={"h1": "DOWN"})
    worker, _, context = _admin_worker([_snapshot("h1")], send_fn=send, query_fn=query)
    context.set_faked({"h1": "DOWN"})
    worker.maybe_keepalive(0.0)
    assert send.call_count == 1
    worker._sleep_fn.assert_not_called()


def test_run_calls_keepalive_every_iteration_and_survives_errors():
    worker, _, _ = _admin_worker([_snapshot("h1")])
    worker._clock_fn = lambda: 123.0
    calls = []

    def fake_keepalive(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("unexpected")
        worker._stop.set()

    worker.maybe_keepalive = fake_keepalive
    worker._queue.put(poller.parse_admin_command(_cmd(action="down", hosts=("h1",))))
    worker._run()
    assert calls == [123.0, 123.0]


# Quick 261003-lnr: a live agent host went CRIT because of Checkmk's "Systemd Timesyncd Time" check,
# a service the dashboard never lists, so the CRIT badge had no visible cause. The host state must
# follow only the services the dashboard shows.
def _agent_services(host, **states):
    base = {
        "Check_MK Agent": "OK",
        "Check_MK": "OK",
        "Uptime": "OK",
        "Systemd Service systemd-timesyncd": "OK",
    }
    base.update({k.replace("_", " "): v for k, v in states.items()})
    return [_service(host, description, state) for description, state in base.items()]


def test_hidden_critical_service_does_not_change_agent_host_state():
    snapshot = _snapshot("linux1", state="CRIT")
    services = _agent_services("linux1") + [_service("linux1", "Systemd Timesyncd Time", "CRIT")]
    poller.apply_visible_service_state([snapshot], services)
    assert snapshot.state == "OK"


def test_systemd_summary_is_hidden_so_it_does_not_change_agent_host_state():
    snapshot = _snapshot("linux1", state="CRIT")
    services = _agent_services("linux1") + [_service("linux1", "Systemd Service Summary", "CRIT")]
    poller.apply_visible_service_state([snapshot], services)
    assert snapshot.state == "OK"


@pytest.mark.parametrize(
    "description",
    ["Systemd Service cron", "Service Spooler", "TCP Port 22 (expected open)", "CPU utilization",
     "Memory", "Filesystem /var", "SMART /dev/sda Stats", "Check_MK", "Uptime"],
)
def test_visible_critical_service_drives_agent_host_state(description):
    snapshot = _snapshot("linux1", state="OK")
    services = _agent_services("linux1") + [_service("linux1", description, "CRIT")]
    poller.apply_visible_service_state([snapshot], services)
    assert snapshot.state == "CRIT"


def test_worst_visible_state_uses_checkmk_order_unknown_below_crit():
    snapshot = _snapshot("linux1", state="CRIT")
    services = _agent_services("linux1", Uptime="UNKNOWN", Check_MK="WARN")
    poller.apply_visible_service_state([snapshot], services)
    assert snapshot.state == "UNKNOWN"


def test_non_agent_host_and_down_host_keep_their_state():
    ping_only = _snapshot("sw1", state="CRIT")
    down = _snapshot("linux2", state="DOWN", host_state_raw="DOWN")
    services = [_service("sw1", "Interface 1", "CRIT")] + _agent_services("linux2")
    poller.apply_visible_service_state([ping_only, down], services)
    assert ping_only.state == "CRIT"
    assert down.state == "DOWN"


def test_run_cycle_publishes_state_from_visible_services():
    client = MagicMock()
    services = _agent_services("linux1") + [_service("linux1", "Systemd Timesyncd Time", "CRIT")]
    poller.run_cycle(client, _make_config(), _poller_state(), [_snapshot("linux1", state="CRIT")], services)
    payload = json.loads(_published(client, "sites/testsite/lan/devices/linux1/status")[0].args[1])
    assert payload["state"] == "OK"


def test_main_exits_2_on_invalid_cmk_site_id(monkeypatch, capsys):
    # CMK_SITE_ID becomes an MQTT topic level; a bad value must stop startup
    # before any client exists.
    monkeypatch.setenv("CMK_SITE_ID", "a/b")
    monkeypatch.setattr(sys, "argv", ["mqtt_poller.py"])
    assert poller.main() == 2
    assert "CMK_SITE_ID" in capsys.readouterr().err
