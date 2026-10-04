"""Poller for the LAN monitoring dashboard: Livestatus-over-TCP -> per-device
retained MQTT topics (`sites/<site_id>/lan/devices/{id}/status`,
`sites/<site_id>/lan/devices/topology`, `sites/<site_id>/lan/events/recent`).

Standalone script, not part of the installable `checkmk_wizard` package
--------------------------------------------------------------------
D-01 locks this as a standalone script rather than a module inside the
installable `checkmk_wizard` package: it must run independently of the
wizard and be deployable to a site where the wizard isn't needed or
installed. Do not import anything from `checkmk_wizard`, and do not wire
this into `[project.scripts]`.

Livestatus over TCP, not the local UNIX socket
-----------------------------------------------
This module talks to Livestatus over its TCP port (default 6557), the
same reasoning `src/checkmk_wizard/livestatus.py` documents: the poller
runs from a separate container/host than the Checkmk site itself, so it
must not require filesystem access to the `checkmk` container's own OMD
site (the container-boundary constraint this whole project is built
around).

Do not copy from `docs/src/mqtt_publisher_changes.py`
-------------------------------------------------------
That file is a documentation-only prototype using three now-deprecated
approaches this module must not repeat: the paho-mqtt v1 callback API
(no `CallbackAPIVersion.VERSION2`), Livestatus access over the local UNIX
socket instead of TCP, and a single full-blob retained topic instead of
this project's per-device topic contract.

MQTT client lifecycle and publish helpers below follow
`scripts/smoke_test_broker.py`'s live-tested paho-mqtt 2.1.0
`CallbackAPIVersion.VERSION2` idioms (this repo's own proven reference,
built and verified against a real deployed broker in Phase 8) rather
than generic docs.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import logging
import math
import os
import queue
import random
import re
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo
from dataclasses import dataclass, field

import boto3
import botocore.config
import botocore.exceptions
import paho.mqtt.client as mqtt

DEFAULT_LIVESTATUS_PORT = 6557
DEFAULT_MQTT_PORT = 1883
DEFAULT_POLL_INTERVAL_SECONDS = 15
# 2026-09-25: raised from 50 by operator decision so the dashboard's date-range
# filter has days of history to work with (~160 KB retained payload at 1000).
DEFAULT_EVENTS_MAX_ENTRIES = 1000
DEFAULT_RECONCILE_TIMEOUT_SECONDS = 5.0
# Not env-configurable (D-04 scopes env vars to the settings it names): this
# is the per-request socket timeout for the poller's own Livestatus calls,
# matching src/checkmk_wizard/livestatus.py's existing hardcoded default.
DEFAULT_LIVESTATUS_TIMEOUT_SECONDS = 10.0
DEFAULT_REST_PORT = 5000
# Not env-configurable, same reasoning as DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
# above: this is the per-request timeout for the poller's own REST folder
# lookup, kept as a named constant rather than inlined.
DEFAULT_REST_TIMEOUT_SECONDS = 10.0
# Phase 14.1 (D-44): default per-request timeout for the poller's ClickHouse
# HTTP writes/queries, env-configurable via CLICKHOUSE_TIMEOUT_SECONDS
# (unlike the Livestatus/REST timeouts above) since ClickHouse's own load
# is outside this project's control.
DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS = 5.0
# Phase 14.1 (D-44/T-14.1-08): the table name is interpolated directly into
# the INSERT statement's SQL text (ClickHouse's HTTP interface has no
# parameterized-identifier syntax), so `_clickhouse_insert` only ever
# writes to one of these four known-safe names -- never an arbitrary
# caller-supplied string.
CLICKHOUSE_INSERT_TABLES = frozenset(
    {"history.metrics", "history.host_state", "history.service_state", "history.availability_daily"}
)

# Phase 14.1 (D-45..D-53, D-57): the daily availability rollup's constants.
AVAILABILITY_SCHEMA_VERSION = 1
DEFAULT_ROLLUP_TZ = "Asia/Singapore"
# Deliberately stays inside the 30-day raw retention window: rule A of the
# TTL downsamples history.host_state at 30 days (see
# deploy/clickhouse-config/initdb/01-schema.sql), and a backfill request for
# a day past that point would read already-downsampled, coarser data
# instead of the raw per-poll samples this rollup expects (D-52).
DEFAULT_ROLLUP_BACKFILL_DAYS = 28
DEFAULT_ROLLUP_DELAY_MINUTES = 5
DEFAULT_AVAILABILITY_BUCKET = "fleet-availability"
ROLLUP_RETRY_SECONDS = 300
FOLDERLESS_GROUP_KEY = "(no folder)"
FLEET_GROUP_KEY = "all"

# Topic suffixes. Every topic the poller uses lives under `sites/<site_id>/`;
# these constants are the part after that prefix and must only be used through
# site_topic() (or compared against relative_topic() output).
TOPIC_TOPOLOGY = "lan/devices/topology"
TOPIC_EVENTS = "lan/events/recent"
TOPIC_POLLER_STATUS = "lan/poller/status"
# Admin command channel topics. Deliberately outside `lan/` so the wsreader's
# `read lan/#` ACL never matches them (D-09); still true under the site prefix.
TOPIC_ADMIN_CMD = "admin/cmd"
TOPIC_ADMIN_ACK = "admin/ack"
TOPIC_ADMIN_FAKED = "admin/faked"

# Same rule as wizard._SITE_NAME_RE, deploy/init-env.sh and the dashboard's
# runtimeConfig.ts SITE_ID_RE. Matched with fullmatch because `$` would accept
# a trailing newline. The id becomes an MQTT topic level, so `/ + #` and
# whitespace must never get through.
_SITE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")
_site_prefix: str | None = None

# Phase 14 (D-13/PLR-14): prefix for the incident id `compute_incidents()`
# below mints (`f"{INCIDENT_ID_PREFIX}{root_id}"`) and topic segment
# `reconcile_state()` matches against when collecting retained incident
# topics at startup.
INCIDENT_ID_PREFIX = "incident-"

UNKNOWN_DEVICE_TYPE = "unknown"

# Phase 14 (D-05/D-09): operator-entered business tier, never inferred from
# any Checkmk-native signal. The 4-tier vocabulary (ordinal -- index is
# rank) is Claude's discretion per D-09, 14-RESEARCH.md A1. Must be kept in
# step by hand with `CRITICALITY_TIERS`/`CRITICALITY_RANK` in
# `dashboard-react/src/lib/incidents.ts` (plan 14-02) -- no shared source of
# truth between Python and that file.
CRITICALITY_TIERS = ("low", "medium", "high", "critical")
DEFAULT_CRITICALITY = "low"

# Phase 13 (D-07 addendum, plan 13-04): the map's saved position and
# unmanaged-switch marker are stored as Checkmk host labels (not a custom
# host attribute -- 13-01 VERDICT V-CUSTOMATTR found no REST endpoint to
# define new custom-attribute definitions, while labels need zero
# predefinition). `dashboard-react/src/lib/topologyLayout.ts` is the
# browser-side twin that must use these exact same strings/regex -- both
# consumers of the `host_config` collection's `extensions.attributes.labels`
# (13-01 VERDICT V-LABELS-IN-COLLECTION: YES, no extra per-host GET needed).
MAP_POSITION_LABEL = "map_position"
UNMANAGED_SWITCH_LABEL = "unmanaged_switch"
UNMANAGED_SWITCH_VALUE = "yes"
_MAP_POSITION_RE = re.compile(r"^-?\d{1,6},-?\d{1,6}$")

# Phase 14 (D-07/D-08/D-09, plan 14-07): the operator-entered criticality/
# dependency labels, following the exact same "Checkmk host label, no new
# store" pattern as MAP_POSITION_LABEL/UNMANAGED_SWITCH_LABEL above. The
# browser-side twin (plan 14-08, `dashboard-react/src/lib/checkmkWrite.ts`)
# must use these exact same key strings and delimiters. Checkmk host labels
# allow any character except a colon (`:`) in key or value
# (docs.checkmk.com/latest/en/labels.html, cited in 14-RESEARCH.md "Verified:
# Checkmk Host Label Constraints") -- none of the delimiters below (`;`, `=`,
# `,`) is a colon, so this scheme is safe by construction.
CRITICALITY_LABEL = "criticality"
SERVICE_CRITICALITY_LABEL = "service_criticality"
DEPENDS_ON_LABEL = "depends_on"
# Mirrors `_HOST_NAME_RE` in `src/checkmk_wizard/wizard.py` and `HOST_NAME_RE`
# in `dashboard-react/src/lib/checkmkWrite.ts` -- the one character class
# Checkmk host ids are constrained to across this whole codebase.
# `\Z`, not `$`: `$` also matches before a trailing newline (review WR-03).
_HOST_ID_RE = re.compile(r"^[-0-9a-zA-Z_.]+\Z")
_MAX_SERVICE_CRITICALITY_ENTRIES = 200
_MAX_DEPENDS_ON_ENTRIES = 50

# Phase 12 (D-05/D-08): the SMART health-service name match string, kept in
# this one clearly-commented location so a future live re-check is a
# one-line fix. Source-verified against Checkmk 2.4.0's own SMART
# check-plugin code (`cmk/plugins/smart/agent_based/smart_ata.py`,
# `smart_nvme.py`, `smart_scsi.py`, all registering `service_name="SMART %s
# Stats"`), NOT live-verified -- no agent-test host was reachable on
# 2026-09-21. CONTEXT.md D-05 originally paraphrased this as `Smart
# <device>`; if a live `uv run python scripts/mqtt_poller.py
# --dump-service-names` run shows a different string, correcting this one
# regex is the entire fix. `"Temperature SMART <device>"` is deliberately
# NOT matched here -- it is informational, not a health signal, and shows
# as a normal service-list row instead (D-08).
SMART_HEALTH_SERVICE_RE = re.compile(r"^SMART .+ Stats$")

# Phase 12 (D-01): the CPU/RAM gauges' backing service names and the
# Filesystem service-name prefix every `Filesystem <mount>` service shares.
# The headline disk gauge reads the service named exactly "Filesystem /";
# every other `Filesystem *` service feeds the `disk_other_worst_*` badge
# instead.
GAUGE_CPU_SERVICE = "CPU utilization"
GAUGE_RAM_SERVICE = "Memory"
GAUGE_FILESYSTEM_PREFIX = "Filesystem "

# Phase 12 (D-02): the systemd roll-up service is explicitly never shown in
# the per-service list -- only the individual wizard-chosen
# `Systemd Service <name>` entries are.
SERVICE_LIST_EXCLUDED_EXACT = ("Systemd Service Summary",)

# Live-verified against a real Checkmk 2.4.0p35 CE site on 2026-09-08: a
# `GET columns` probe (`mqtt_poller.py --check-columns`, run via
# scripts/smoke_test_poller.py's `check_livestatus_columns`) reported all
# eight columns below as present -- name, state, scheduled_downtime_depth,
# acknowledged, worst_service_state, parents, tags, filename -- closing
# RESEARCH.md Assumptions A1 (`parents`) and A2 (`filename`). `tags` is
# also confirmed present (closing the existence half of A3), and is
# actually consulted by `extract_device_type()` below, but the *shape*
# A3 also claimed -- the device-type key inside `tags` -- remains
# unverified: every one of the 21 onboarded hosts on the live site
# returned `tags` with neither `device_type` nor `tag_device_type` set,
# because no host on that site currently carries a Checkmk `device_type`
# tag group (assigning that tag is Phase 10's job, not yet run). This
# exercised `extract_device_type()`'s `UNKNOWN_DEVICE_TYPE` fallback path
# correctly, but not the real key shape -- re-confirm once Phase 10 lands.
#
# Follow-up, live-verified against a real Checkmk 2.4.0p36.cre CE site
# (site `dmc`) on 2026-09-11 (plan 10-06): a filtered `GET hosts` LQL
# query against a host freshly tagged `device_type=NetworkDevice`
# through the Checkmk UI returned `tags` keyed by the bare group id --
# `{'device_type': 'NetworkDevice'}`, no `tag_` prefix. A3 is closed:
# Livestatus keys custom tags the same way the wizard's own attribute
# name suggests, not with the REST attribute's `tag_` prefix. The same
# query against an untagged host (`checkmk_wizard`) returned
# `{'device_type': 'other'}`, not an absent key -- Livestatus resolves a
# tag group's configured default rather than omitting an unset tag,
# which is the opposite of the REST API's `extensions.attributes`
# behavior (10-01 live-verified REST omits the key entirely when a host
# has never had the attribute explicitly set). Practical consequence:
# once the `device_type` tag group exists on a site, `extract_device_type`
# can no longer observe `UNKNOWN_DEVICE_TYPE` for a normal untagged host
# -- Livestatus always resolves one of the group's real choices (`other`
# included). `UNKNOWN_DEVICE_TYPE` surviving in a payload therefore means
# the tag group itself is missing from the site (a pre-Phase-10 site, or
# a site Phase 10 was never run against), not "this host has no device
# type" -- see `extract_device_type()`'s docstring below.
#
# The same 2026-09-11 run confirmed the `alias` column (added by Phase
# 10, D-10, listed below) is present and populated on 2.4.0p36.cre: the
# operator-set alias value (`core-router-1`) was distinguishable from
# the hostname in the retained MQTT payload.
#
# The same live run also closed Assumption A4 (reconciliation timing):
# with the default 60s poll interval, no spurious `lan/devices/topology`
# republish was observed across two full poll intervals (130s) of no
# change, and the poller's own heartbeat (`lan/poller/status`) was 38s
# old at check time -- both consistent with the timeout defaults already
# shipped below, so no correction was needed.
#
# Bug fixed 2026-09-11 (Phase 10, D-04): `filename` was confirmed present
# by the 2026-09-08 probe above, but Phase 10 stopped consuming it. The
# old `derive_folder()` located a literal `wato` segment in this
# Livestatus-reported OMD filesystem path to guess a folder -- that
# breaks outright when the Checkmk site id is itself named `wato`
# (`.planning/phases/09-poller-core/09-REVIEW.md` finding WR-07, since a
# site named `wato` puts a second, unrelated `wato` segment earlier in
# the same path), and breaks silently on folder rename/restructure
# (`.planning/research/PITFALLS.md` Pitfall 10), because it parses an
# on-disk layout with no schema guarantee. The folder now comes from
# Checkmk's own REST-computed `extensions.folder` association
# (`fetch_host_folders()` below) -- a semantic value with no filesystem
# coupling, closing the whole class of bug rather than patching this one
# instance.
REQUIRED_HOST_COLUMNS = ("name", "state")
OPTIONAL_HOST_COLUMNS = (
    "scheduled_downtime_depth",
    "acknowledged",
    "worst_service_state",
    "parents",
    "tags",
    # Added by Phase 10 (D-10). Not covered by the 2026-09-08 column probe
    # above; live-verified present and populated on a real 2.4.0p36.cre
    # site on 2026-09-11 (plan 10-06, see the dated follow-up note above).
    "alias",
    # Added by Phase 11 (D-17): Checkmk's own staleness value, preferred by
    # DASH-04 over a timestamp-age fallback. Optional, never required --
    # live-verified present on a real 2.4.0p36.cre site on 2026-09-16 via
    # the poller-container `--check-columns` probe (plan 11-01 Task 3).
    # `--check-columns` only confirms the column exists, not that it is
    # populated on every host, so the timestamp-age fallback (D-12) stays
    # in place: a present column can still return null per-host.
    "staleness",
    # Added by Phase 14 (PLR-14): per-host epoch seconds of the current
    # hard/soft state's start, used as incident duration. Standard
    # Nagios-lineage Livestatus column -- live-verified present on a real
    # 2.4.0p36.cre site on 2026-09-26 via `--check-columns` (plan 14-05):
    # incident duration displays real values (e.g. "9 h 56 min"). Absent
    # would make every incident's `since` null, never a failure.
    "last_state_change",
    # Added 2026-09-28 (quick 260928-m6f) so the dashboard can show a host's
    # IP next to a renamed host's name: the standard Livestatus `hosts`
    # column holding the host's configured IP (the host check output
    # `router: 192.168.0.1 rta ...` shows Checkmk already knows it).
    # Optional, never required -- a site without it publishes an empty
    # string and never fails.
    "address",
)

# Phase 12 (D-08/D-11): the services-table required/optional split mirrors
# REQUIRED_HOST_COLUMNS/OPTIONAL_HOST_COLUMNS above. `perf_data` is
# deliberately OPTIONAL, never REQUIRED, per 12-RESEARCH.md Pitfall 4: the
# per-service list (`description`/`state`/`plugin_output`) degrades fine
# without it, whereas promoting `perf_data` to REQUIRED would take gauges,
# the SMART badge and the whole service list down together on any site
# that does not expose it.
REQUIRED_SERVICE_COLUMNS = ("host_name", "description", "state")
OPTIONAL_SERVICE_COLUMNS = ("plugin_output", "perf_data")

# Standard Nagios plugin return codes, used unchanged by Checkmk/Livestatus
# for the `worst_service_state` column (verified: checkmk.com/werk/8003).
_SERVICE_STATE_NAMES = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}

# Phase 14.1 (D-43): history.host_state's state encoding (0 UP, 1 DOWN,
# 2 UNREACHABLE), matching `host_state_label()`'s "UP"/"DOWN"/"UNREACH"
# labels (D-17) -- see `build_history_rows()` below.
HOST_STATE_CODES = {"UP": 0, "DOWN": 1, "UNREACH": 2}

# MQTT reserves `+`/`#` as wildcard characters and treats `/` as the
# topic-level separator (T-09-01 topic-injection guard).
_TOPIC_UNSAFE_CHARS = ("+", "#", "/")

# Mirrors src/checkmk_wizard/wizard.py's own
# `_DISCOVERY_RETRY_DELAYS_SECONDS = (10, 20, 30)` convention: a plain
# tuple of backoff seconds for the poller's one-time startup Livestatus
# probe (see run_forever), not a retry decorator or backoff library.
_STARTUP_RETRY_DELAYS_SECONDS = (5, 10, 15)

_logger = logging.getLogger(__name__)


class LivestatusError(RuntimeError):
    """Raised for any Livestatus network failure or malformed response."""


class RestError(RuntimeError):
    """Raised for any Checkmk REST network failure or malformed response.

    Single normalized failure type for the poller's REST calls, mirroring
    `LivestatusError`'s role for Livestatus.
    """


class ClickHouseError(RuntimeError):
    """Single normalized failure type for the poller's ClickHouse HTTP calls (D-44).

    Callers log it and carry on -- it never interrupts the mandatory
    Livestatus/MQTT cycle, mirroring `RestError`'s non-fatal role for the
    REST folder lookup.
    """


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to `default` (with a warning) on a bad value.

    A typo in the compose file's environment block must never crash-loop
    the container — see PollerConfig.from_env().
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid integer for %s=%r; using default %r", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Float counterpart of `_env_int` — see its docstring."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning("Invalid float for %s=%r; using default %r", name, raw, default)
        return default


@dataclass
class PollerConfig:
    """Poller runtime settings, sourced entirely from environment variables (D-04)."""

    livestatus_host: str
    livestatus_port: int
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    poll_interval_seconds: int
    events_max_entries: int
    reconcile_timeout_seconds: float
    log_level: str
    # REST credential fields for the folder-lookup helper (D-03). Appended
    # after log_level so no positional PollerConfig(...) call site breaks.
    cmk_rest_host: str = "checkmk"
    cmk_rest_port: int = DEFAULT_REST_PORT
    cmk_site_id: str = "dmc"
    cmk_rest_username: str = ""
    cmk_rest_secret: str = ""
    # Phase 14.1 (D-44). Appended after cmk_rest_secret so no
    # positional PollerConfig(...) call site breaks. An empty
    # clickhouse_url (the default) means history writes are disabled
    # entirely (write_history() below is a no-op) -- the poller behaves
    # exactly as before Phase 14.1 with CLICKHOUSE_URL unset.
    clickhouse_url: str = ""
    clickhouse_writer_user: str = "poller_writer"
    clickhouse_writer_password: str = ""
    clickhouse_timeout_seconds: float = DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS
    # Phase 14.1 (D-41/D-56/D-57). Appended after clickhouse_timeout_seconds
    # so no positional PollerConfig(...) call site breaks. An empty
    # s3_endpoint (the default) disables availability rollups entirely --
    # maybe_run_rollups() below is a no-op until both CLICKHOUSE_URL and
    # S3_ENDPOINT are set.
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_addressing_style: str = "path"
    availability_bucket: str = DEFAULT_AVAILABILITY_BUCKET
    rollup_tz: str = DEFAULT_ROLLUP_TZ
    rollup_backfill_days: int = DEFAULT_ROLLUP_BACKFILL_DAYS
    rollup_delay_minutes: int = DEFAULT_ROLLUP_DELAY_MINUTES

    def __repr__(self) -> str:
        # T-09-02: this object must be safe to log — never render the raw
        # MQTT password, the REST secret (cmk_rest_secret), or (Phase 14.1)
        # the ClickHouse writer password. Defined explicitly so @dataclass
        # does not generate a repr that would include any of them.
        return (
            "PollerConfig("
            f"livestatus_host={self.livestatus_host!r}, "
            f"livestatus_port={self.livestatus_port!r}, "
            f"mqtt_host={self.mqtt_host!r}, "
            f"mqtt_port={self.mqtt_port!r}, "
            f"mqtt_username={self.mqtt_username!r}, "
            "mqtt_password='***', "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, "
            f"events_max_entries={self.events_max_entries!r}, "
            f"reconcile_timeout_seconds={self.reconcile_timeout_seconds!r}, "
            f"log_level={self.log_level!r}, "
            f"cmk_rest_host={self.cmk_rest_host!r}, "
            f"cmk_rest_port={self.cmk_rest_port!r}, "
            f"cmk_site_id={self.cmk_site_id!r}, "
            f"cmk_rest_username={self.cmk_rest_username!r}, "
            "cmk_rest_secret='***', "
            f"clickhouse_url={self.clickhouse_url!r}, "
            f"clickhouse_writer_user={self.clickhouse_writer_user!r}, "
            "clickhouse_writer_password='***', "
            f"clickhouse_timeout_seconds={self.clickhouse_timeout_seconds!r}, "
            f"s3_endpoint={self.s3_endpoint!r}, "
            "s3_access_key='***', "
            "s3_secret_key='***', "
            f"s3_region={self.s3_region!r}, "
            f"availability_bucket={self.availability_bucket!r}, "
            f"rollup_tz={self.rollup_tz!r}, "
            f"rollup_backfill_days={self.rollup_backfill_days!r})"
        )

    @classmethod
    def from_env(cls) -> PollerConfig:
        return cls(
            livestatus_host=os.environ.get("LIVESTATUS_HOST", "checkmk"),
            livestatus_port=_env_int("LIVESTATUS_PORT", DEFAULT_LIVESTATUS_PORT),
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=_env_int("MQTT_PORT", DEFAULT_MQTT_PORT),
            mqtt_username=os.environ.get("MQTT_USERNAME", "poller"),
            mqtt_password=os.environ.get("MQTT_PASSWORD", "poller"),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
            events_max_entries=_env_int("EVENTS_MAX_ENTRIES", DEFAULT_EVENTS_MAX_ENTRIES),
            reconcile_timeout_seconds=_env_float(
                "RECONCILE_TIMEOUT_SECONDS", DEFAULT_RECONCILE_TIMEOUT_SECONDS
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            cmk_rest_host=os.environ.get("CMK_REST_HOST", "checkmk"),
            cmk_rest_port=_env_int("CMK_REST_PORT", DEFAULT_REST_PORT),
            # Reuses the exact env-var name deploy/compose.yaml's checkmk/
            # worker services already set, so operators are not asked to
            # configure the same value under two names.
            cmk_site_id=os.environ.get("CMK_SITE_ID", "dmc"),
            cmk_rest_username=os.environ.get("CMK_REST_USERNAME", ""),
            cmk_rest_secret=os.environ.get("CMK_REST_SECRET", ""),
            # Phase 14.1 (D-44): trailing slash stripped so URL-building
            # call sites can always do f"{clickhouse_url}/?query=..." without
            # worrying about a double slash.
            clickhouse_url=os.environ.get("CLICKHOUSE_URL", "").rstrip("/"),
            clickhouse_writer_user=os.environ.get("CLICKHOUSE_WRITER_USER", "poller_writer"),
            clickhouse_writer_password=os.environ.get("CLICKHOUSE_WRITER_PASSWORD", ""),
            clickhouse_timeout_seconds=_env_float(
                "CLICKHOUSE_TIMEOUT_SECONDS", DEFAULT_CLICKHOUSE_TIMEOUT_SECONDS
            ),
            # Phase 14.1 (D-41/D-56): S3_* names are the same ones the
            # worker service already sets in deploy/compose.yaml -- reused
            # here rather than inventing a second set of variable names for
            # the same MinIO/AWS S3 credentials.
            s3_endpoint=os.environ.get("S3_ENDPOINT", ""),
            s3_access_key=os.environ.get("S3_ACCESS_KEY", ""),
            s3_secret_key=os.environ.get("S3_SECRET_KEY", ""),
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_addressing_style=os.environ.get("S3_ADDRESSING_STYLE", "path"),
            availability_bucket=os.environ.get("AVAILABILITY_BUCKET", DEFAULT_AVAILABILITY_BUCKET),
            rollup_tz=os.environ.get("ROLLUP_TZ", DEFAULT_ROLLUP_TZ),
            rollup_backfill_days=_env_int("ROLLUP_BACKFILL_DAYS", DEFAULT_ROLLUP_BACKFILL_DAYS),
            rollup_delay_minutes=_env_int("ROLLUP_DELAY_MINUTES", DEFAULT_ROLLUP_DELAY_MINUTES),
        )


def _parse_criticality(raw: object) -> str:
    """Strict parser for the `criticality` label's value -- never raises.

    Any value outside the fixed `CRITICALITY_TIERS` vocabulary (a wrong
    case like `"HIGH"`, an unknown tier like `"urgent"`, a non-string, or
    an absent label) degrades to `DEFAULT_CRITICALITY` (T-14-19), the same
    safe-default posture `map_position`/`unmanaged` already apply above.
    """
    return raw if isinstance(raw, str) and raw in CRITICALITY_TIERS else DEFAULT_CRITICALITY


def _parse_service_criticality(raw: object) -> dict[str, str]:
    """Strict parser for the `service_criticality` label's `;`-separated `name=tier` value.

    Never raises (T-14-19): a non-string value degrades to `{}`; each
    `;`-separated entry is independently validated and a malformed one
    (missing `=`, empty name after stripping, or a name containing `:`,
    which cannot legally occur in a Checkmk service name derived from this
    project's own check plugins but is rejected defensively anyway) is
    skipped rather than aborting the whole label. At most
    `_MAX_SERVICE_CRITICALITY_ENTRIES` valid entries are kept (T-14-20),
    in encounter order.
    """
    if not isinstance(raw, str):
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(";"):
        if "=" not in entry:
            continue
        name, _, tier = entry.partition("=")
        name = name.strip()
        tier = tier.strip()
        if not name or ":" in name or tier not in CRITICALITY_TIERS:
            continue
        result[name] = tier
        if len(result) >= _MAX_SERVICE_CRITICALITY_ENTRIES:
            break
    return result


def _parse_depends_on(raw: object, host_id: str) -> list[str]:
    """Strict parser for the `depends_on` label's comma-separated host-id list.

    Never raises (T-14-19): a non-string value degrades to `[]`. Each
    comma-separated entry is stripped and validated against `_HOST_ID_RE`;
    an invalid id (e.g. containing a space) is dropped. A self-reference
    (`host_id` depending on itself) is dropped -- it can never form a real
    dependency chain. Duplicates are removed, order preserved (first
    occurrence wins). At most `_MAX_DEPENDS_ON_ENTRIES` ids are kept
    (T-14-20), bounding `compute_incidents()`'s dependents closure walk.
    """
    if not isinstance(raw, str):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate or not _HOST_ID_RE.match(candidate) or candidate == host_id:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) >= _MAX_DEPENDS_ON_ENTRIES:
            break
    return result


@dataclass
class HostConfigInfo:
    """One host's REST-sourced config: folder plus the map-editing and Phase 14 labels.

    Returned by `fetch_host_config()` below -- a superset of what
    `fetch_host_folders()` used to return alone, from the same single
    `host_config` collection GET (no extra REST call per Phase 13's D-07
    addendum / 13-01 VERDICT V-LABELS-IN-COLLECTION).

    Phase 14 (D-07/D-08/D-09, plan 14-07): `criticality`/`service_criticality`/
    `depends_on` are populated from the same `host_config` GET's labels via
    `_parse_criticality()`/`_parse_service_criticality()`/`_parse_depends_on()`
    -- still no extra REST call.
    """

    folder: str = ""
    map_position: str | None = None
    unmanaged: bool = False
    criticality: str = DEFAULT_CRITICALITY
    service_criticality: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DeviceSnapshot:
    """One device's current state, as derived from a single Livestatus `hosts` row."""

    id: str
    state: str
    # Field names locked by D-07, mirroring Livestatus's own column
    # naming so the payload traces back cleanly to source columns:
    # in_downtime <- scheduled_downtime_depth > 0, acknowledged <- acknowledged.
    in_downtime: bool
    acknowledged: bool
    device_type: str
    folder: str
    parents: list[str] = field(default_factory=list)
    # D-09/D-10: Checkmk's native `alias` host attribute, set by the
    # wizard's Phase 4 prompt, carried through so Phase 11 can prefer it
    # over the hostname for display. This phase only makes it available;
    # it does not decide display preference.
    alias: str = ""
    # Added 2026-09-28 (quick 260928-m6f): the host's configured IP from
    # Livestatus's `address` column, carried through so the dashboard can
    # show it next to a renamed host's display name. `""` when the column
    # is absent or the host has none (e.g. an unmanaged switch).
    address: str = ""
    # D-17: Checkmk's own authoritative staleness value (Livestatus
    # `staleness` column), preferred by DASH-04 over a timestamp-age
    # fallback. `None` when the column is absent from the live site --
    # graceful degradation, not an error (Pitfall 4).
    staleness: float | None = None
    # D-17: the real host state, so a subscriber can tell DOWN and
    # UNREACHABLE apart. `compute_overall_state()` below collapses both
    # into the single `state` value `"DOWN"` by design (D-08's worst-of
    # aggregation keeps `state` an OK/WARN/CRIT/UNKNOWN/DOWN enum); this
    # field is additive, not a replacement.
    host_state_raw: str = "UP"
    # Phase 13 (D-07 addendum): the map's saved "x,y" position and
    # unmanaged-switch marker, sourced from `fetch_host_config()`'s
    # `HostConfigInfo` via `query_devices()`'s `host_config` parameter.
    # `None`/`False` when the host has no `host_config` entry (or the
    # cycle's REST lookup degraded) -- same graceful-degradation posture
    # as `folder` above, never a hard failure.
    map_position: str | None = None
    unmanaged: bool = False
    # Phase 14 (PLR-14/PLR-16): per-host epoch seconds of the current
    # hard/soft state's start (Livestatus `last_state_change`, see
    # OPTIONAL_HOST_COLUMNS above), used only as an incident's duration
    # source. `None` when the column is absent or non-positive -- graceful
    # degradation, never a hard failure.
    last_state_change: int | None = None
    # Phase 14 (D-05/D-07/D-08, plan 14-07): criticality/service_criticality/
    # depends_on are populated from Checkmk host labels (`CRITICALITY_LABEL`/
    # `SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL`), read the same way
    # `map_position`/`unmanaged` already are -- via `query_devices()`'s
    # `host_config` parameter. A host with no `host_config` entry (or an
    # unset label) keeps these safe defaults; `compute_incidents()` above
    # already consumes `criticality`/`depends_on` against this exact
    # contract (plan 14-01).
    criticality: str = DEFAULT_CRITICALITY
    depends_on: list[str] = field(default_factory=list)
    service_criticality: dict[str, str] = field(default_factory=dict)


@dataclass
class ServiceSnapshot:
    """One service's current state, as derived from a single Livestatus `services` row."""

    host_name: str
    description: str
    # The OK/WARN/CRIT/UNKNOWN name, mapped through the existing
    # `_SERVICE_STATE_NAMES` table -- never the raw int (mirrors
    # DeviceSnapshot.state's own name-not-int convention).
    state: str
    state_raw: int
    plugin_output: str = ""
    # Already-parsed `parse_perf_data()` output. The raw perf_data string
    # is deliberately not retained -- nothing downstream needs it.
    perf_data: dict = field(default_factory=dict)


def configure_logging(level: str) -> None:
    """Wire up `logging.basicConfig`. Called by `main()`; never at import time."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def set_site_id(site_id: str) -> None:
    """Set the `sites/<site_id>/` prefix every poller topic is built under.

    Raises ValueError for anything that is not a valid Checkmk site id, so a
    bad CMK_SITE_ID fails at startup instead of creating a malformed topic.
    """
    global _site_prefix
    if not _SITE_ID_RE.fullmatch(site_id):
        raise ValueError(
            f"CMK_SITE_ID {site_id!r} is not a valid Checkmk site id "
            "(letter first, then letters/digits/underscore, at most 16 characters)"
        )
    _site_prefix = f"sites/{site_id}/"


def site_topic(suffix: str) -> str:
    if _site_prefix is None:
        raise RuntimeError("set_site_id() was not called")
    return _site_prefix + suffix


def relative_topic(full: str) -> str | None:
    """Return `full` without this site's prefix, or None if it is not under it."""
    if _site_prefix is not None and full.startswith(_site_prefix):
        return full[len(_site_prefix) :]
    return None


def device_status_topic(device_id: str) -> str:
    return site_topic(f"lan/devices/{device_id}/status")


def device_services_topic(device_id: str) -> str:
    return site_topic(f"lan/devices/{device_id}/services")


def incident_status_topic(incident_id: str) -> str:
    return site_topic(f"lan/incidents/{incident_id}/status")


def is_publishable_device_id(device_id: str) -> bool:
    """Reject any device id that would corrupt the MQTT topic hierarchy if interpolated.

    Livestatus reports every host known to Checkmk, including hosts
    created outside this project's own wizard (whose onboarding flow
    already validates hostnames via `_HOSTNAME_RE`) — e.g. via the
    Checkmk UI directly, or `bulk_create_hosts`. Any such name could
    contain `/`, `+`, `#` or control characters, so this check must run
    on every host name Livestatus returns, not just wizard-onboarded
    ones (T-09-01).
    """
    if not device_id or not device_id.strip():
        return False
    if any(ch in device_id for ch in _TOPIC_UNSAFE_CHARS):
        return False
    return not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in device_id)


def compute_overall_state(host_state: int, worst_service_state: int) -> str:
    """Worst-of aggregation (D-08): host DOWN/UNREACHABLE always wins outright."""
    if host_state != 0:  # 1=DOWN, 2=UNREACHABLE (src/checkmk_wizard/livestatus.py convention)
        return "DOWN"
    return _SERVICE_STATE_NAMES.get(worst_service_state, "UNKNOWN")


# Quick 261003-lnr (operator-chosen 2026-10-03): an agent host's overall state is the worst of the
# services the dashboard SHOWS, not Livestatus's `worst_service_state` (which counts every service).
# Live finding: a host went CRIT because of Checkmk's "Systemd Timesyncd Time" check, a service the
# dashboard never lists, so the CRIT badge had no visible cause. The operator picks which services
# to monitor in the wizard and does not want hidden ones to alter the host's status. "Shown" mirrors
# dashboard-react/src/lib/agentDetail.ts (`displayedServices`, `CHOSEN_SERVICE_RE`) plus the
# gauge-backed services (CPU/RAM/filesystems/SMART) and the agent-connection and uptime rows; keep
# the two in step. Non-agent hosts (SNMP/ping) show their full service table, so they are unchanged.
AGENT_INFO_SERVICE = "Check_MK Agent"
_VISIBLE_AGENT_SERVICES_EXACT = frozenset({"Check_MK", "Uptime", GAUGE_CPU_SERVICE, GAUGE_RAM_SERVICE})
_CHOSEN_SERVICE_RE = re.compile(r"^(Systemd Service|Service) (?!Summary$)")
_TCP_PORT_SERVICE_RE = re.compile(r"^TCP Port \d+")
# Checkmk's own worst-state order (Livestatus docs): OK < WARN < UNKNOWN < CRIT.
_SERVICE_STATE_SEVERITY = {"OK": 0, "WARN": 1, "UNKNOWN": 2, "CRIT": 3}


def is_visible_agent_service(description: str) -> bool:
    """True if the dashboard shows this service of an agent host (so it may drive the host state)."""
    return (
        description in _VISIBLE_AGENT_SERVICES_EXACT
        or description.startswith(GAUGE_FILESYSTEM_PREFIX)
        or bool(SMART_HEALTH_SERVICE_RE.match(description))
        or bool(_CHOSEN_SERVICE_RE.match(description))
        or bool(_TCP_PORT_SERVICE_RE.match(description))
    )


def apply_visible_service_state(
    snapshots: list[DeviceSnapshot], services: list[ServiceSnapshot]
) -> None:
    """Recompute each agent host's `state` from its dashboard-visible services only.

    A host that is DOWN/UNREACHABLE keeps `"DOWN"`, and a host with no `Check_MK Agent` service
    (not an agent host) keeps the Livestatus-derived state. Runs before anything reads
    `snapshot.state`, so the status topic, events, history, topology and incidents all agree.
    Skipped by the caller on a cycle whose services query failed (`services is None`): the host
    column's state is then published unchanged, which can briefly differ for a host with a hidden
    non-OK service.
    """
    by_host: dict[str, list[ServiceSnapshot]] = {}
    for service in services:
        by_host.setdefault(service.host_name, []).append(service)
    for snapshot in snapshots:
        if snapshot.state == "DOWN":
            continue
        host_services = by_host.get(snapshot.id, [])
        if not any(s.description == AGENT_INFO_SERVICE for s in host_services):
            continue
        worst = max(
            (
                _SERVICE_STATE_SEVERITY.get(s.state, _SERVICE_STATE_SEVERITY["UNKNOWN"])
                for s in host_services
                if is_visible_agent_service(s.description)
            ),
            default=0,
        )
        snapshot.state = next(name for name, rank in _SERVICE_STATE_SEVERITY.items() if rank == worst)


def host_state_label(host_state: int) -> str:
    """Map a raw Livestatus host-state int to "UP"/"DOWN"/"UNREACH" (D-17).

    This deliberately does NOT replace `compute_overall_state()` above --
    that function's collapse of 1=DOWN/2=UNREACHABLE into a single `"DOWN"`
    `state` value is unchanged and still the aggregation D-08 requires.
    This function feeds the separate, additive `host_state_raw` field so a
    subscriber can tell DOWN and UNREACHABLE apart when it needs to
    (D-11/Pitfall 6), using the same 1=DOWN/2=UNREACHABLE mapping asserted
    in `compute_overall_state()`'s own inline comment.
    """
    return {0: "UP", 1: "DOWN", 2: "UNREACH"}.get(host_state, "UP")


def topology_nodes(snapshots: list[DeviceSnapshot]) -> list[dict]:
    return [
        {
            "id": snapshot.id,
            "parents": list(snapshot.parents),
            "device_type": snapshot.device_type,
            "folder": snapshot.folder,
            "alias": snapshot.alias,
            "map_position": snapshot.map_position,
            "unmanaged": snapshot.unmanaged,
            # Phase 14 (D-07/D-08/D-09, plan 14-07): carried to every viewer
            # on this same topic so criticality/dependency edits reach the
            # dashboard without a per-device round trip.
            "criticality": snapshot.criticality,
            "service_criticality": dict(snapshot.service_criticality),
            "depends_on": list(snapshot.depends_on),
        }
        for snapshot in snapshots
    ]


def topology_signature(nodes: list[dict]) -> tuple:
    """Order-independent signature used to decide whether topology actually changed.

    `map_position`/`unmanaged` are read with `.get()`, not direct indexing,
    unlike the five original fields: a node dict fed in here may come from
    `topology_nodes()`/`_normalise_restored_node()` (always populated) or
    from a hand-built fixture in an older test/caller that predates these
    two Phase 13 fields -- `.get()` degrades that case to the same
    None/False default `_normalise_restored_node()` backfills, rather than
    raising `KeyError` for every caller that hasn't been updated yet.

    Phase 14 (D-07/D-08/D-09, plan 14-07): `criticality`/`depends_on`/
    `service_criticality` are read the same defensive `.get()` way, with the
    same rationale -- a criticality or dependency label edit must trigger
    exactly one republish, and an older/hand-built node dict without these
    keys must not raise or spuriously differ from a fresh node carrying the
    same defaults.
    """
    return tuple(
        sorted(
            (
                node["id"],
                tuple(sorted(node["parents"])),
                node["device_type"],
                node["folder"],
                node["alias"],
                node.get("map_position"),
                node.get("unmanaged", False),
                node.get("criticality", DEFAULT_CRITICALITY),
                tuple(node.get("depends_on", [])),
                tuple(sorted((node.get("service_criticality") or {}).items())),
            )
            for node in nodes
        )
    )


def _reachable_roots_from(
    start_id: str,
    roots: set[str],
    traversable: set[str],
    by_id: dict[str, DeviceSnapshot],
    *,
    through_roots: bool = False,
) -> set[str]:
    """Walk upward from `start_id`'s parents, through `traversable` hosts only, collecting
    every member of `roots` reached. A `visited` set guards against a `parents` cycle
    (D-10/PLR-14): each candidate is examined at most once, so this always terminates
    regardless of how the Livestatus-reported topology is shaped.

    Once a root is reached the walk does not continue past it -- a root's own ancestors
    are not part of the incident being assigned/nested from `start_id` -- unless
    `through_roots` is set, which collects every root on the whole upward chain. Nesting
    needs the full chain: bug fixed 2026-09-28 (14-REVIEW CR-01). Stopping at the first
    root meant `r2` in a DOWN chain `r0 <- r1 <- r2` saw only the nested root `r1`, never
    the top root `r0`, and was wrongly promoted to a top root of its own, splitting one
    outage into two incidents.
    """
    reached: set[str] = set()
    visited: set[str] = set()
    frontier = [parent_id for parent_id in by_id[start_id].parents if parent_id in by_id]
    while frontier:
        candidate = frontier.pop()
        if candidate in visited:
            continue
        visited.add(candidate)
        if candidate not in traversable:
            continue
        if candidate in roots:
            reached.add(candidate)
            if not through_roots:
                continue
        frontier.extend(parent_id for parent_id in by_id[candidate].parents if parent_id in by_id)
    return reached


def _effective_criticality_index(snapshot: DeviceSnapshot, *, is_dependent: bool) -> int:
    """Rank of `snapshot.criticality`, D-15's one-tier reduction applied for a still-UP dependent.

    An out-of-vocabulary criticality value (never raised by this project's own label writer,
    but a hand-edited WATO label could carry one) degrades to `DEFAULT_CRITICALITY`'s rank,
    the same safe-default posture `fetch_host_config()` already applies to `map_position`.
    """
    raw = snapshot.criticality
    index = CRITICALITY_TIERS.index(raw if raw in CRITICALITY_TIERS else DEFAULT_CRITICALITY)
    if is_dependent and snapshot.host_state_raw == "UP":
        return max(index - 1, 0)
    return index


def _dependents_closure(affected: set[str], dependents_of: dict[str, list[str]]) -> set[str]:
    """BFS outward from `affected` over the (already-inverted) `depends_on` graph.

    A `visited` set is both the accumulator and the cycle guard, matching
    `_reachable_roots_from()`'s own termination argument (T-14-02).
    """
    visited = set(affected)
    frontier = list(affected)
    while frontier:
        current = frontier.pop()
        for dependent_id in dependents_of.get(current, []):
            if dependent_id not in visited:
                visited.add(dependent_id)
                frontier.append(dependent_id)
    return visited


def compute_incidents(snapshots: list[DeviceSnapshot]) -> list[dict]:
    """Group every non-OK (DOWN/UNREACH) host into one incident per root cause (PLR-14/PLR-15).

    Pure function, no I/O: re-derived from a fresh `list[DeviceSnapshot]` every poll cycle
    (D-13/PLR-14's "no persisted incident state" requirement), using only `parents` and
    `host_state_raw` for grouping and `criticality`/`depends_on` for the worst-affected
    calculation -- both already present on every snapshot handed to this function.

    Algorithm (D-10/D-11/PLR-14/PLR-15):

    1. `non_ok` = hosts whose `host_state_raw` is "DOWN" or "UNREACH". Service-level
       WARN/CRIT never triggers incident grouping -- this is about host-level DOWN/
       UNREACHABLE cascades only.
    2. Inferred roots (D-11): an `unmanaged` host with >= 2 non-OK children, at least one
       of which is DOWN, becomes an inferred root -- Checkmk cannot see past an unmanaged
       switch, so several children going non-OK together is the sibling evidence D-11
       requires before blaming the switch. A lone non-OK child under an unmanaged switch
       is NOT inferred; it stays its own plain root.
    3. Plain roots: every DOWN host that is not a direct child of an inferred root.
    4. Traversable set = `non_ok` union the inferred roots (an inferred root's own
       `host_state_raw` is typically "UP" -- Checkmk can still ping the switch -- so it
       would not otherwise be walkable). A root is NESTED when walking upward through
       traversable parents (`_reachable_roots_from`, cycle-guarded) reaches another root;
       top roots are the roots that are not nested. A parent cycle can leave every root in
       a nested group nested; the fallback promotes the first (by id) root with no *other*
       reachable top root to a top root itself, guaranteeing every root ends up assigned.
    5. Assignment: every non-OK host that is not itself a top root walks its traversable
       parent chain (same cycle-guarded walk) collecting reachable top roots; joining the
       lexicographically smallest id keeps the choice deterministic when more than one is
       reachable. A host that reaches no top root belongs to no incident and is simply
       left out -- Checkmk's own data does not support inventing a root for it.
    6. Classification (Plan 14-01 decision, D-04 applied to PLR-14): in an INFERRED
       incident every consequence goes to `not_observable`, never `confirmed_down` --
       Checkmk reports a host behind an unchecked switch as DOWN only because it cannot
       see the switch, and claiming "confirmed down" would be exactly the overclaim D-04
       forbids. In a non-inferred incident a DOWN consequence is `confirmed_down`, an
       UNREACH one is `not_observable`.
    7. Worst-affected criticality (PLR-16, transitive closure per 14-RESEARCH.md Open
       Question 1): `dependents` is the transitive closure of `affected` (root plus
       consequences) over the reverse `depends_on` graph, minus `affected` itself.
       `worst_criticality` is the highest-ranked criticality among `affected` union
       `dependents`, where a dependent that is still UP counts one tier lower than its own
       tier (D-15) and every other member counts at its own tier.
    8. `since`: the earliest positive `last_state_change` across the root (only when the
       root is itself DOWN/UNREACH -- an inferred root's own timestamp is not evidence of
       when the incident began) and every consequence, rendered ISO-8601 UTC; `None` when
       no member has one (column absent, or every value non-positive).

    Known limitation (14-RESEARCH.md Pitfall 1, shipped as-is for v1 per Open Question 2):
    a host that is independently DOWN for its own unrelated reason, but happens to sit
    behind a root that also failed, is folded into that root's incident as a consequence --
    Livestatus's `parents`/`host_state_raw` alone cannot disambiguate "down because of the
    incident" from "coincidentally also down". This is not attempted here; the wording is
    still factually true (the host is DOWN), just imprecise about cause.
    """
    by_id = {snapshot.id: snapshot for snapshot in snapshots}
    non_ok = {snapshot.id for snapshot in snapshots if snapshot.host_state_raw in ("DOWN", "UNREACH")}

    children: dict[str, list[str]] = {}
    for snapshot in snapshots:
        for parent_id in snapshot.parents:
            if parent_id in by_id:
                children.setdefault(parent_id, []).append(snapshot.id)

    inferred_roots: set[str] = set()
    for snapshot in snapshots:
        if not snapshot.unmanaged:
            continue
        non_ok_children = [child_id for child_id in children.get(snapshot.id, []) if child_id in non_ok]
        if len(non_ok_children) >= 2 and any(
            by_id[child_id].host_state_raw == "DOWN" for child_id in non_ok_children
        ):
            inferred_roots.add(snapshot.id)

    plain_roots = {
        snapshot.id
        for snapshot in snapshots
        if snapshot.host_state_raw == "DOWN"
        and not any(parent_id in inferred_roots for parent_id in snapshot.parents)
    }

    roots = plain_roots | inferred_roots
    traversable = non_ok | inferred_roots

    reachable_from_root = {
        root_id: _reachable_roots_from(root_id, roots, traversable, by_id, through_roots=True) - {root_id}
        for root_id in roots
    }
    top_roots = {root_id for root_id in roots if not reachable_from_root[root_id]}
    nested_roots = roots - top_roots
    for root_id in sorted(nested_roots):
        if not (reachable_from_root[root_id] & top_roots):
            top_roots.add(root_id)

    assignment: dict[str, str] = {}
    for host_id in non_ok:
        if host_id in top_roots:
            assignment[host_id] = host_id
            continue
        reachable_top = _reachable_roots_from(host_id, top_roots, traversable, by_id)
        if reachable_top:
            assignment[host_id] = min(reachable_top)

    dependents_of: dict[str, list[str]] = {}
    for snapshot in snapshots:
        for target_id in snapshot.depends_on:
            if target_id == snapshot.id or target_id not in by_id:
                continue
            dependents_of.setdefault(target_id, []).append(snapshot.id)

    incidents: list[dict] = []
    for root_id in top_roots:
        consequence_ids = sorted(
            host_id for host_id, assigned_root in assignment.items() if assigned_root == root_id and host_id != root_id
        )
        inferred = root_id in inferred_roots

        confirmed_down: list[str] = []
        not_observable: list[str] = []
        for host_id in consequence_ids:
            if inferred:
                not_observable.append(host_id)
            elif by_id[host_id].host_state_raw == "DOWN":
                confirmed_down.append(host_id)
            else:
                not_observable.append(host_id)

        affected = {root_id, *consequence_ids}
        closure = _dependents_closure(affected, dependents_of)
        dependents = sorted(closure - affected)

        indices = [_effective_criticality_index(by_id[host_id], is_dependent=False) for host_id in affected]
        indices += [_effective_criticality_index(by_id[host_id], is_dependent=True) for host_id in dependents]
        worst_criticality = CRITICALITY_TIERS[max(indices)]

        root_snapshot = by_id[root_id]
        since_candidates = [by_id[host_id].last_state_change for host_id in consequence_ids]
        if root_snapshot.host_state_raw in ("DOWN", "UNREACH"):
            since_candidates.append(root_snapshot.last_state_change)
        positive_candidates = [value for value in since_candidates if value]
        since = (
            datetime.datetime.fromtimestamp(min(positive_candidates), datetime.UTC).isoformat()
            if positive_candidates
            else None
        )

        incidents.append(
            {
                "id": f"{INCIDENT_ID_PREFIX}{root_id}",
                "root": root_id,
                "root_state": root_snapshot.host_state_raw,
                "inferred": inferred,
                "confirmed_down": confirmed_down,
                "not_observable": not_observable,
                "dependents": dependents,
                "worst_criticality": worst_criticality,
                "since": since,
            }
        )

    return sorted(incidents, key=lambda incident: incident["id"])


def incident_signature(incident: dict) -> tuple:
    """Stable signature deciding whether an incident actually changed (PLR-16 republish rule).

    `dependents`/`worst_criticality` are included deliberately: an operator's criticality or
    depends_on label edit must reach every viewer even when the underlying DOWN/UNREACH set
    is unchanged. Uses `.get()` with defaults, matching `topology_signature()`'s own tolerance
    for a hand-built dict that predates a field.
    """
    return (
        incident.get("root"),
        incident.get("root_state"),
        incident.get("inferred"),
        tuple(incident.get("confirmed_down", [])),
        tuple(incident.get("not_observable", [])),
        tuple(incident.get("dependents", [])),
        incident.get("worst_criticality"),
        incident.get("since"),
    )


# --- Admin command channel (D-01..D-14) -------------------------------------------------

ADMIN_ACTIONS = ("up", "down", "unreach", "restore", "restore_all")
ADMIN_MAX_HOSTS_PER_COMMAND = 200
_ADMIN_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}\Z")
# Mirrors wizard.py `_LIVESTATUS_RETRY_DELAYS_SECONDS`: the core reloads on activation and
# resets connections, so a send can fail transiently.
ADMIN_LIVESTATUS_RETRY_DELAYS_SECONDS = (3, 5, 10)
_ADMIN_SAFE_ADDRESS_RE = re.compile(r"^[0-9A-Za-z.:_-]{1,253}\Z")


class AdminCommandError(ValueError):
    """A rejected admin command; `reason` is the short text that goes into the ack detail."""

    def __init__(self, reason: str, command_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.command_id = command_id


@dataclass
class AdminCommand:
    id: str
    action: str
    hosts: list[str]


@dataclass
class AdminAction:
    host: str
    op: str  # "up" | "down" | "unreach" | "restore"
    cascaded: bool


def parse_admin_command(payload: bytes) -> AdminCommand:
    """Validate an `admin/cmd` payload. The browser is untrusted input (T-16-01).

    Host ids are regex-checked here even though the worker later resolves them against
    the snapshot list: defence in depth, so a malformed id can never reach any text that
    is built from it. Never touches snapshots.
    """
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise AdminCommandError("malformed command") from None
    if not isinstance(data, dict):
        raise AdminCommandError("malformed command")
    command_id = data.get("id")
    if not isinstance(command_id, str) or not _ADMIN_COMMAND_ID_RE.match(command_id):
        raise AdminCommandError("malformed command")
    action = data.get("action")
    if action not in ADMIN_ACTIONS:
        raise AdminCommandError("unknown action", command_id)
    hosts = data.get("hosts")
    if action == "restore_all" and not hosts:
        hosts = []
    if not isinstance(hosts, list):
        raise AdminCommandError("invalid host list", command_id)
    if action == "restore_all":
        # Hosts are ignored for restore_all.
        return AdminCommand(id=command_id, action=action, hosts=[])
    if (
        not 1 <= len(hosts) <= ADMIN_MAX_HOSTS_PER_COMMAND
        or not all(isinstance(h, str) and _HOST_ID_RE.match(h) for h in hosts)
    ):
        raise AdminCommandError("invalid host list", command_id)
    return AdminCommand(id=command_id, action=action, hosts=list(dict.fromkeys(hosts)))


def _admin_children_map(by_id: dict[str, DeviceSnapshot]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for snap in by_id.values():
        for parent in snap.parents:
            if parent in by_id:
                children.setdefault(parent, []).append(snap.id)
    return children


def _admin_descendants(
    start_id: str, by_id: dict[str, DeviceSnapshot], children: dict[str, list[str]]
) -> list[str]:
    """Descendants of `start_id` (visited-set BFS, cycle safe), not expanding past an
    unmanaged host: the unmanaged switch itself is included, its subtree is not (D-02)."""
    visited = {start_id}
    queue = [start_id]
    reached: list[str] = []
    while queue:
        current = queue.pop(0)
        if current != start_id and by_id[current].unmanaged:
            continue
        for child in children.get(current, []):
            if child in visited:
                continue
            visited.add(child)
            reached.append(child)
            queue.append(child)
    return reached


def _has_other_faked_down_ancestor(
    host_id: str,
    by_id: dict[str, DeviceSnapshot],
    faked: dict[str, str],
    excluded: set[str],
) -> bool:
    """True if a managed ancestor outside `excluded` is still faked DOWN and covers
    `host_id` (D-01 reverse cascade). The walk does not continue above an unmanaged
    ancestor, mirroring the downward stop rule (D-02)."""
    visited = {host_id}
    queue = list(by_id[host_id].parents)
    while queue:
        current = queue.pop()
        if current in visited or current not in by_id:
            continue
        visited.add(current)
        node = by_id[current]
        if node.unmanaged:
            continue
        if faked.get(current) == "DOWN" and current not in excluded:
            return True
        queue.extend(node.parents)
    return False


def plan_admin_actions(
    action: str,
    host_ids: list[str],
    snapshots: list[DeviceSnapshot],
    faked: dict[str, str],
) -> list[AdminAction]:
    """Turn one admin command into per-host operations (pure, D-01/D-02).

    Hosts named explicitly always get the command's own state. DOWN on a managed host
    cascades UNREACH to its descendants; the walk includes an unmanaged switch (UNREACH)
    but stops there, because Checkmk cannot see past it (clarified 2026-10-02). UP/restore
    on a managed host reverses the cascade for descendants faked UNREACH (the cascade's
    restore uses the demo baseline, see build_admin_commands), unless another
    faked-DOWN managed ancestor still covers them. Unknown host ids are ignored; the
    caller reports them as skipped.
    """
    by_id = {s.id: s for s in snapshots}
    if action == "restore_all":
        return [AdminAction(h, "restore", False) for h in sorted(faked) if h in by_id]

    explicit = [h for h in dict.fromkeys(host_ids) if h in by_id]
    explicit_set = set(explicit)
    result = [AdminAction(h, action, False) for h in explicit]
    if action not in ("down", "up", "restore"):
        return result

    children = _admin_children_map(by_id)
    cascaded: set[str] = set()
    for host in explicit:
        if by_id[host].unmanaged:
            continue
        for desc in _admin_descendants(host, by_id, children):
            if desc in explicit_set or desc in cascaded:
                continue
            covered = faked.get(desc) != "UNREACH" or _has_other_faked_down_ancestor(
                desc, by_id, faked, explicit_set
            )
            if action == "down" or not covered:
                cascaded.add(desc)
    cascade_op = "unreach" if action == "down" else "restore"
    result.extend(AdminAction(h, cascade_op, True) for h in sorted(cascaded))
    return result


def _admin_output_address(address: str, host_id: str) -> str:
    return address if _ADMIN_SAFE_ADDRESS_RE.match(address or "") else host_id


def _admin_up_output(ip: str) -> str:
    """The OK plugin text shared by the up op, restore and the UP keepalive."""
    return f"OK - {ip} rta {random.uniform(0.2, 3.0):.3f}ms lost 0%"


def _admin_fake_result(state: str, ip: str) -> tuple[int, int, str]:
    """(host code, PING code, plugin text) for a faked UP/DOWN/UNREACH state."""
    if state == "UP":
        return 0, 0, _admin_up_output(ip)
    output = f"CRITICAL - {ip}: rta nan, lost 100%"
    if state == "DOWN":
        return 1, 2, output
    if state == "UNREACH":
        return 2, 2, output
    raise ValueError(f"unknown faked state: {state!r}")


def _admin_guard(commands: list[str]) -> list[str]:
    for command in commands:
        if "\n" in command or "\r" in command or "'" in command:
            raise ValueError(f"unsafe Livestatus command: {command!r}")
    return commands


def build_admin_commands(action: AdminAction, address: str) -> list[str]:
    """Livestatus external command bodies for one AdminAction (D-04/D-05).

    Mirrors wizard.py `_fake_demo_hosts_up` and the runbook's live-verified fakeping
    sequence. For up/down/unreach the host check and the PING service check are
    DISABLED first so neither the scheduled check nor the demo "Always assume host to
    be up" rule overwrites the injected result (D-05). Restore re-enables the host check
    (so the rule keeps demo hosts UP and the host leaves the faked set), injects host UP
    and PING OK, and deliberately leaves PING disabled: the wizard --demo baseline.
    Fixed after the 2026-10-02 live UAT (16-UAT-GAPS.md gap 3): the old restore sent
    ENABLE_SVC_CHECK, so Checkmk really pinged the demo host's non-existent IP and the
    host went CRITICAL. Livestatus returns nothing for COMMAND, so success means
    "sent", not "applied". Fails closed (ValueError) on any character that could break
    out of the command.
    """
    host = action.host
    if not _HOST_ID_RE.match(host):
        raise ValueError(f"invalid host id: {host!r}")
    if action.op == "restore":
        ip = _admin_output_address(address, host)
        output = _admin_up_output(ip)
        commands = [
            f"ENABLE_HOST_CHECK;{host}",
            f"PROCESS_HOST_CHECK_RESULT;{host};0;{output}",
            f"PROCESS_SERVICE_CHECK_RESULT;{host};PING;0;{output}",
        ]
    elif action.op in ("up", "down", "unreach"):
        ip = _admin_output_address(address, host)
        host_code, svc_code, output = _admin_fake_result(action.op.upper(), ip)
        commands = [
            f"DISABLE_HOST_CHECK;{host}",
            f"DISABLE_SVC_CHECK;{host};PING",
            f"PROCESS_HOST_CHECK_RESULT;{host};{host_code};{output}",
            f"PROCESS_SERVICE_CHECK_RESULT;{host};PING;{svc_code};{output}",
        ]
    else:
        raise ValueError(f"unknown op: {action.op!r}")
    return _admin_guard(commands)


def build_admin_keepalive_commands(host: str, state: str, address: str) -> list[str]:
    """Re-inject a faked host's current result (UAT gap 4, staleness).

    Only the two PROCESS_* lines: the checks are already disabled while faked, and
    re-sending DISABLE_* from a stale faked set could re-disable a just-restored host.
    """
    if not _HOST_ID_RE.match(host):
        raise ValueError(f"invalid host id: {host!r}")
    ip = _admin_output_address(address, host)
    host_code, svc_code, output = _admin_fake_result(state, ip)
    return _admin_guard(
        [
            f"PROCESS_HOST_CHECK_RESULT;{host};{host_code};{output}",
            f"PROCESS_SERVICE_CHECK_RESULT;{host};PING;{svc_code};{output}",
        ]
    )


def send_livestatus_commands(
    host: str, port: int, commands: list[str], timeout: float
) -> None:
    """Send external commands, one connection per command.

    Deliberate twin of src/checkmk_wizard/livestatus.py `send_commands` (this standalone
    container script cannot import the wizard package). One connection per command is
    load-bearing: without `KeepAlive: on` a connection ends after one request, so several
    COMMAND lines on one socket are not reliably processed. CR/LF is rejected before any
    connection is opened so a value cannot smuggle in a second request. The caller owns
    retries (ADMIN_LIVESTATUS_RETRY_DELAYS_SECONDS).
    """
    for command in commands:
        if "\n" in command or "\r" in command:
            raise ValueError(f"Livestatus command must not contain newlines: {command!r}")
    for command in commands:
        payload = f"COMMAND [{int(time.time())}] {command}\n\n"
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                sock.sendall(payload.encode())
                sock.shutdown(socket.SHUT_WR)
        except (TimeoutError, OSError) as exc:
            raise LivestatusError(f"Livestatus command send failed: {exc}") from exc


# --- Admin command channel: faked-set derivation and command worker --------------------

ADMIN_FAKED_COLUMN = "active_checks_enabled"
ADMIN_PING_SERVICE = "PING"
ADMIN_FAKED_HOSTS_QUERY = (
    "GET hosts\nColumns: name state active_checks_enabled\n"
    "Filter: active_checks_enabled = 0\nOutputFormat: json\n\n"
)
ADMIN_PING_SERVICES_QUERY = (
    "GET services\nColumns: host_name active_checks_enabled\n"
    "Filter: description = PING\nOutputFormat: json\n\n"
)
ADMIN_QUEUE_MAX = 8
ADMIN_SEEN_IDS_MAX = 64
# Like wizard `_fake_demo_hosts_up`'s 2 s pause: lets the core apply the external
# commands before the faked-set query runs.
ADMIN_REFRESH_DELAY_SECONDS = 2.0
ADMIN_ACK_DETAIL_MAX = 200
# Checkmk staleness = result age / check_interval (60 s on the demo site) and the
# dashboard flags STALE at STALENESS_FACTOR 3. Re-injecting every 30 s keeps staleness
# near 0.5, still under 1.0 if one tick fails; the requirement is at least every 60 s
# (16-UAT-GAPS.md gap 4: live staleness 2.9-11.2 on faked hosts).
ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS = 30
_ADMIN_OP_STATE = {"up": "UP", "down": "DOWN", "unreach": "UNREACH", "restore": "RESTORED"}
_ADMIN_FAKED_STATES = ("UP", "DOWN", "UNREACH")


def _livestatus_json_rows(body: str, what: str) -> list:
    if not body.strip():
        return []
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed {what} response: {exc}") from exc
    if not isinstance(rows, list):
        raise LivestatusError(f"Malformed {what} response: expected a list")
    return rows


def query_faked_hosts(host: str, port: int, timeout: float) -> dict[str, str]:
    """Hosts that currently look faked, derived from Livestatus (D-10).

    Faked means the HOST's active checks are disabled AND (the host's PING service has
    active checks disabled OR the host has no PING service). Wizard `--demo` hosts
    disable only the PING check (the host check stays enabled under the "Always assume
    host to be up" rule), so they are not counted; unmanaged switches have no PING
    service, so a faked switch is still counted. Hosts whose checks an operator disabled
    for other reasons are counted too (documented limitation). A restored host has its
    host check enabled and PING disabled, the same shape as a wizard --demo host, so it
    is not counted. Assumption A1: the
    `active_checks_enabled` column exists on the live site (probed by `--check-columns`).
    """
    try:
        host_rows = _livestatus_json_rows(
            _livestatus_request(host, port, ADMIN_FAKED_HOSTS_QUERY, timeout), "faked hosts"
        )
        ping_rows = _livestatus_json_rows(
            _livestatus_request(host, port, ADMIN_PING_SERVICES_QUERY, timeout), "PING services"
        )
        ping_active = {row[0]: int(row[1]) for row in ping_rows}
        faked: dict[str, str] = {}
        for row in host_rows:
            name = row[0]
            if not isinstance(name, str) or not is_publishable_device_id(name):
                continue
            if int(row[2]) != 0:
                continue  # host check enabled: a restored/demo host, never faked
            if ping_active.get(name, 0) != 0:
                continue
            faked[name] = host_state_label(int(row[1]))
    except (IndexError, TypeError, ValueError) as exc:
        raise LivestatusError(f"Malformed faked-hosts response: {exc}") from exc
    return faked


class AdminContext:
    """State shared between the poll loop thread and the admin worker thread (lock-guarded)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, DeviceSnapshot] = {}
        self._faked: dict[str, str] = {}
        self._last_published: dict[str, str] | None = None
        # Serializes the should_publish + publish pair so two threads cannot publish
        # out of order and leave a stale retained admin/faked (review WR-02).
        self.publish_lock = threading.Lock()
        self.use_ledger = False

    def update_snapshots(self, snapshots: list[DeviceSnapshot]) -> None:
        with self._lock:
            self._snapshots = {s.id: s for s in snapshots}

    def snapshot_map(self) -> dict[str, DeviceSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    def faked(self) -> dict[str, str]:
        with self._lock:
            return dict(self._faked)

    def set_faked(self, faked: dict[str, str]) -> None:
        with self._lock:
            self._faked = dict(faked)

    def prune_ledger(self, known: dict) -> dict[str, str]:
        """Drop ledger hosts missing from `known`, atomically; returns the ledger."""
        with self._lock:
            self._faked = {h: s for h, s in self._faked.items() if h in known}
            return dict(self._faked)

    def seed_ledger(self, faked: dict[str, str]) -> None:
        self.set_faked(faked)

    def apply_ledger(self, actions: list[AdminAction]) -> None:
        """Record applied actions in the ledger (only meaningful when `use_ledger`)."""
        with self._lock:
            for action in actions:
                if action.op == "restore":
                    self._faked.pop(action.host, None)
                elif action.op in _ADMIN_OP_STATE:
                    self._faked[action.host] = _ADMIN_OP_STATE[action.op]

    def should_publish(self, faked: dict[str, str]) -> bool:
        with self._lock:
            if self._last_published is not None and self._last_published == faked:
                return False
            self._last_published = dict(faked)
            return True


def publish_admin_faked(client, hosts: dict[str, str], source: str, timestamp: str) -> None:
    _publish_json(
        client,
        site_topic(TOPIC_ADMIN_FAKED),
        {"hosts": hosts, "source": source, "timestamp": timestamp},
        qos=1,
        retain=True,
    )


def publish_admin_ack(client, ack: dict) -> None:
    # Not retained: a late admin tab must never show a stale result.
    _publish_json(client, site_topic(TOPIC_ADMIN_ACK), ack, qos=1, retain=False)


def refresh_admin_faked(client, context: AdminContext, config: PollerConfig) -> None:
    """Recompute the faked map and publish `admin/faked` only when it changed (D-10)."""
    if context.use_ledger:
        known = context.snapshot_map()
        faked = context.prune_ledger(known) if known else context.faked()
        source = "ledger"
    else:
        try:
            faked = query_faked_hosts(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
        except LivestatusError as exc:
            _logger.warning("Faked-host query failed; keeping last map: %s", exc)
            return
        context.set_faked(faked)
        source = "livestatus"
    with context.publish_lock:
        if context.should_publish(faked):
            publish_admin_faked(client, faked, source, utc_now_iso())


def parse_admin_faked_payload(payload: bytes) -> dict[str, str]:
    """Parse a retained `admin/faked` payload; {} on anything malformed."""
    try:
        data = json.loads(payload.decode("utf-8"))
        hosts = data["hosts"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(hosts, dict):
        return {}
    return {
        k: v
        for k, v in hosts.items()
        if isinstance(k, str) and _HOST_ID_RE.match(k) and v in _ADMIN_FAKED_STATES
    }


class AdminCommandWorker:
    """Executes admin commands off paho's network thread.

    Livestatus retries during a core reload can take ~20 s, which must never block paho's
    network loop or the poll loop. One daemon thread serializes commands so two actions
    never interleave. The same thread also runs the faked-host keepalive
    (`maybe_keepalive`) so it is serialized with admin commands.
    """

    def __init__(
        self,
        config: PollerConfig,
        context: AdminContext,
        *,
        send_fn=send_livestatus_commands,
        sleep_fn=time.sleep,
        refresh_fn=refresh_admin_faked,
        clock_fn=time.monotonic,
        query_fn=query_faked_hosts,
    ) -> None:
        self._config = config
        self._context = context
        self._send_fn = send_fn
        self._sleep_fn = sleep_fn
        self._refresh_fn = refresh_fn
        self._clock_fn = clock_fn
        self._query_fn = query_fn
        self._next_keepalive_at = 0.0
        self._queue: queue.Queue[AdminCommand] = queue.Queue(maxsize=ADMIN_QUEUE_MAX)
        self._seen_ids: collections.deque[str] = collections.deque(maxlen=ADMIN_SEEN_IDS_MAX)
        self._stop = threading.Event()
        self._client = None
        self._thread: threading.Thread | None = None

    def attach_client(self, client) -> None:
        self._client = client

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="admin-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _ack(self, ack: dict) -> None:
        if self._client is not None:
            publish_admin_ack(self._client, ack)

    @staticmethod
    def _fail_ack(command_id: str, action: str, detail: str) -> dict:
        return {
            "id": command_id,
            "ok": False,
            "action": action,
            "detail": detail[:ADMIN_ACK_DETAIL_MAX],
            "applied": [],
            "skipped": [],
        }

    def submit(self, payload: bytes, retained: bool) -> None:
        """Runs on paho's thread; must stay cheap."""
        if retained:
            # Stale-command replay guard (T-16-05): a retained admin/cmd must never execute.
            _logger.warning("Ignoring retained admin/cmd delivery")
            return
        try:
            command = parse_admin_command(payload)
        except AdminCommandError as exc:
            if exc.command_id is not None:
                self._ack(self._fail_ack(exc.command_id, "", exc.reason))
            return
        if command.id in self._seen_ids:
            return
        self._seen_ids.append(command.id)
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            self._ack(self._fail_ack(command.id, command.action, "poller busy, try again"))

    def process_one(self, command: AdminCommand) -> dict:
        known = self._context.snapshot_map()
        if not known:
            return self._fail_ack(command.id, command.action, "poller has no host list yet")
        known_hosts = [h for h in command.hosts if h in known]
        skipped = [h for h in command.hosts if h not in known]
        if command.action != "restore_all" and not known_hosts:
            return self._fail_ack(command.id, command.action, "no known hosts in command")
        actions = plan_admin_actions(
            command.action, known_hosts, list(known.values()), self._context.faked()
        )
        ack = {
            "id": command.id,
            "ok": True,
            "action": command.action,
            "detail": "nothing to do",
            "applied": [],
            "skipped": skipped,
        }
        if not actions:
            return ack
        commands: list[str] = []
        built: list[AdminAction] = []
        for a in actions:
            try:
                commands.extend(build_admin_commands(a, known[a.host].address))
            except ValueError as exc:
                # One unsafe host must not drop the whole batch (review WR-04).
                _logger.warning("admin command %s: skipping %s: %s", command.id, a.host, exc)
                skipped.append(a.host)
                continue
            built.append(a)
        actions = built
        if not actions:
            ack["skipped"] = skipped
            ack["detail"] = "no host could be commanded"
            return ack
        failure: LivestatusError | None = None
        for delay in (*ADMIN_LIVESTATUS_RETRY_DELAYS_SECONDS, None):
            try:
                self._send_fn(
                    self._config.livestatus_host,
                    self._config.livestatus_port,
                    commands,
                    DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
                )
                failure = None
                break
            except LivestatusError as exc:
                failure = exc
                if delay is not None:
                    self._sleep_fn(delay)
        if failure is not None:
            ack = self._fail_ack(
                command.id, command.action, f"Livestatus unreachable: {failure}"
            )
            ack["skipped"] = skipped
            return ack
        if self._context.use_ledger:
            self._context.apply_ledger(actions)
        self._sleep_fn(ADMIN_REFRESH_DELAY_SECONDS)
        self._refresh_fn(self._client, self._context, self._config)
        ack["detail"] = f"sent {len(commands)} Livestatus commands"
        ack["applied"] = [
            {"host": a.host, "state": _ADMIN_OP_STATE[a.op], "cascaded": a.cascaded}
            for a in actions
        ]
        _logger.info(
            "admin command id=%s action=%s applied=%d skipped=%d",
            command.id,
            command.action,
            len(actions),
            len(skipped),
        )
        return ack

    def _handle(self, command: AdminCommand) -> None:
        try:
            ack = self.process_one(command)
        except Exception:
            # The only broad catch in the worker: one bad command must never kill the
            # thread that serves every later command.
            _logger.exception("admin command %s failed", command.id)
            ack = self._fail_ack(command.id, command.action, "internal error")
        self._ack(ack)

    def maybe_keepalive(self, now: float) -> None:
        """Re-inject every faked host's current result at most once per interval.

        Single send per tick, no retries or sleeps (the next tick retries); no Livestatus
        I/O at all when nothing is faked. Publishes nothing and leaves the context alone.
        """
        if now < self._next_keepalive_at:
            return
        self._next_keepalive_at = now + ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS
        if not self._context.faked():
            return
        known = self._context.snapshot_map()
        if not known:
            return
        if self._context.use_ledger:
            faked = self._context.faked()
        else:
            # Re-read right before sending so a restore that landed between poll cycles
            # is not overwritten by a stale faked set.
            try:
                faked = self._query_fn(
                    self._config.livestatus_host,
                    self._config.livestatus_port,
                    DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
                )
            except LivestatusError as exc:
                _logger.warning("admin keepalive: faked-set query failed: %s", exc)
                return
        commands: list[str] = []
        refreshed = 0
        for host, state in sorted(faked.items()):
            if host not in known or state not in _ADMIN_FAKED_STATES:
                continue
            try:
                commands.extend(
                    build_admin_keepalive_commands(host, state, known[host].address)
                )
            except ValueError as exc:
                _logger.warning("admin keepalive: skipping %s: %s", host, exc)
                continue
            refreshed += 1
        if not commands:
            return
        try:
            self._send_fn(
                self._config.livestatus_host,
                self._config.livestatus_port,
                commands,
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
            )
        except LivestatusError as exc:
            _logger.warning("admin keepalive: send failed: %s", exc)
            return
        _logger.debug("admin keepalive refreshed %d faked hosts", refreshed)

    def _keepalive_safely(self) -> None:
        try:
            self.maybe_keepalive(self._clock_fn())
        except Exception:
            # Same rationale as _handle: the worker thread serves every later command.
            _logger.exception("admin keepalive failed")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                command = self._queue.get(timeout=1.0)
            except queue.Empty:
                self._keepalive_safely()
                continue
            self._handle(command)
            self._keepalive_safely()


def extract_device_type(tags: dict) -> str:
    """Read the `device_type` tag from a Livestatus `tags` column value.

    Live-verified against a real Checkmk 2.4.0p36.cre CE site (site `dmc`)
    on 2026-09-11 (plan 10-06): Livestatus keys a custom tag group by its
    bare group id (`device_type`), not the `tag_` prefix the REST API uses
    for the same attribute (`tag_device_type`) -- closing RESEARCH.md
    Assumption A3. The same run showed Livestatus resolves the tag
    group's configured default for an untagged host rather than omitting
    the key, so once the `device_type` tag group exists on a site, every
    host reports a real value -- `other` for an untagged host, never a
    missing key.

    `UNKNOWN_DEVICE_TYPE` is therefore the exceptional case, not the
    normal one: it means the `device_type` tag group does not exist on
    this site at all (a pre-Phase-10 site, or one Phase 10 was never run
    against), not "this host has no device type". Callers displaying
    `UNKNOWN_DEVICE_TYPE` (e.g. a future dashboard) should treat it as a
    site-configuration warning, not a device category alongside `other`.
    """
    if "device_type" in tags:
        return tags["device_type"]
    return UNKNOWN_DEVICE_TYPE


def classify_host_services(services: list[ServiceSnapshot]) -> tuple[dict, list[dict]]:
    """Split one host's service snapshots into gauge fields and the D-08 service-row list.

    Returns `(gauge_fields, service_rows)`.

    `gauge_fields` is exactly the `lan/devices/{id}/status` additive-key
    dict (D-12): CPU reads `perf_data["util"]` off `GAUGE_CPU_SERVICE`, RAM
    reads `perf_data["mem_used_percent"]` off `GAUGE_RAM_SERVICE`, disk
    reads `perf_data["fs_used_percent"]` off the service named exactly
    "Filesystem /". `disk_other_worst_*` is the highest `fs_used_percent`
    across every other `GAUGE_FILESYSTEM_PREFIX` service (D-01), carrying
    that mount's own warn/crit and its mount string (the service
    description with the `GAUGE_FILESYSTEM_PREFIX` stripped). Every key is
    present with value `None` when its backing service or metric is absent
    -- absence is expressed as `null`, never an omitted key, so the
    dashboard's hide-on-absence rule (D-03/D-06) has one thing to test.

    `smart_total` counts services matching `SMART_HEALTH_SERVICE_RE`;
    `smart_failing` counts those whose `state_raw` is 1 (WARN) or 2 (CRIT)
    -- UNKNOWN (3) counts toward the total but not toward failing, since an
    unreadable SMART check is not itself evidence of a failing disk. Both
    are `None` when no SMART health service exists (D-06's hide-entirely
    rule).

    `service_rows` is the D-08 list: every service except
    `GAUGE_CPU_SERVICE`, `GAUGE_RAM_SERVICE`, any `GAUGE_FILESYSTEM_PREFIX`
    service, any `SMART_HEALTH_SERVICE_RE` match, and any
    `SERVICE_LIST_EXCLUDED_EXACT` entry. Each row carries only
    `description`/`state`/`plugin_output` -- `perf_data` is deliberately
    not published on this topic. OK rows are included (D-08 is the full
    "what is monitored" picture, not a failure list). Rows are sorted by
    `description` for a stable payload.
    """
    gauge_fields: dict = {
        "cpu_percent": None,
        "cpu_warn": None,
        "cpu_crit": None,
        "ram_percent": None,
        "ram_warn": None,
        "ram_crit": None,
        "disk_percent": None,
        "disk_warn": None,
        "disk_crit": None,
        "disk_other_worst_percent": None,
        "disk_other_worst_warn": None,
        "disk_other_worst_crit": None,
        "disk_other_worst_mount": None,
        "smart_total": None,
        "smart_failing": None,
    }

    smart_services = [s for s in services if SMART_HEALTH_SERVICE_RE.match(s.description)]
    if smart_services:
        gauge_fields["smart_total"] = len(smart_services)
        gauge_fields["smart_failing"] = sum(1 for s in smart_services if s.state_raw in (1, 2))

    worst_other_mount: tuple[float, float | None, float | None, str] | None = None
    for service in services:
        if service.description == GAUGE_CPU_SERVICE:
            metric = service.perf_data.get("util")
            if metric:
                gauge_fields["cpu_percent"] = metric.get("value")
                gauge_fields["cpu_warn"] = metric.get("warn")
                gauge_fields["cpu_crit"] = metric.get("crit")
        elif service.description == GAUGE_RAM_SERVICE:
            metric = service.perf_data.get("mem_used_percent")
            if metric:
                gauge_fields["ram_percent"] = metric.get("value")
                gauge_fields["ram_warn"] = metric.get("warn")
                gauge_fields["ram_crit"] = metric.get("crit")
        elif service.description == f"{GAUGE_FILESYSTEM_PREFIX}/":
            metric = service.perf_data.get("fs_used_percent")
            if metric:
                gauge_fields["disk_percent"] = metric.get("value")
                gauge_fields["disk_warn"] = metric.get("warn")
                gauge_fields["disk_crit"] = metric.get("crit")
        elif service.description.startswith(GAUGE_FILESYSTEM_PREFIX):
            metric = service.perf_data.get("fs_used_percent")
            if not metric or metric.get("value") is None:
                continue
            if worst_other_mount is None or metric["value"] > worst_other_mount[0]:
                mount = service.description[len(GAUGE_FILESYSTEM_PREFIX) :]
                worst_other_mount = (metric["value"], metric.get("warn"), metric.get("crit"), mount)

    if worst_other_mount is not None:
        value, warn, crit, mount = worst_other_mount
        gauge_fields["disk_other_worst_percent"] = value
        gauge_fields["disk_other_worst_warn"] = warn
        gauge_fields["disk_other_worst_crit"] = crit
        gauge_fields["disk_other_worst_mount"] = mount

    gauge_backed_exact = {GAUGE_CPU_SERVICE, GAUGE_RAM_SERVICE}
    service_rows = sorted(
        (
            {"description": s.description, "state": s.state, "plugin_output": s.plugin_output}
            for s in services
            if s.description not in gauge_backed_exact
            and not s.description.startswith(GAUGE_FILESYSTEM_PREFIX)
            and not SMART_HEALTH_SERVICE_RE.match(s.description)
            and s.description not in SERVICE_LIST_EXCLUDED_EXACT
        ),
        key=lambda row: row["description"],
    )
    return gauge_fields, service_rows


def services_signature(rows: list[dict]) -> tuple:
    """Order-independent signature deciding whether the service row list changed.

    Mirrors `topology_signature()`'s technique: a sorted tuple of
    (description, state) pairs, order-independent so a same-content list
    from a different underlying row order still compares equal.

    Deliberately excludes plugin_output's text (12-RESEARCH.md Pitfall 2): a
    chatty check's embedded numbers would otherwise force a republish
    almost every cycle, defeating D-12's whole point in splitting gauges
    from the service list.

    It does include whether plugin_output is non-empty (bug fixed
    2026-10-02, quick 261002-c2m): a never-checked service reports state
    OK with empty output, and its first real result often keeps state OK
    (e.g. a demo host's injected PING result). With only (description,
    state) that first output never republished, so the dashboard's Output
    column stayed blank until some later state change or a poller restart.
    """
    return tuple(sorted((row["description"], row["state"], bool(row["plugin_output"])) for row in rows))


# Leading numeric prefix of a Nagios perfdata value token: an optional
# sign, digits, at most one decimal point, and an optional exponent.
# Scanning for this prefix (rather than enumerating Nagios's own unit
# strings -- %, s/ms/us, B/KB/MB/GB/TB, c) means an unrecognized unit is
# still handled by `_strip_uom` below instead of failing to parse.
_PERF_DATA_NUMERIC_PREFIX_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")

# Tokenizes a perfdata string on whitespace, EXCEPT inside a single-quoted
# label (which may itself contain spaces per the format spec) -- a bare
# `raw.split()` would incorrectly break `'total used'=5;;;;` into two
# tokens. Tried in order per match: a quoted-label token first, falling
# back to a plain non-space token.
_PERF_DATA_TOKEN_RE = re.compile(r"'[^']*'=\S*|\S+")


def _strip_uom(token: str) -> str:
    """Strip a trailing unit-of-measure from a perfdata value token.

    Nagios permits `%`, `s`/`ms`/`us`, `B`/`KB`/`MB`/`GB`/`TB` and `c` as
    units (nagios-plugins.org/doc/guidelines.html, Performance Data Format
    Specification). Returns only the leading numeric portion; a token with
    no numeric prefix at all returns the original token unchanged.
    """
    match = _PERF_DATA_NUMERIC_PREFIX_RE.match(token)
    return match.group(0) if match else token


def parse_perf_data(raw: str) -> dict[str, dict]:
    """Parse a Nagios-format performance-data string into per-metric value/warn/crit/min/max.

    Format (nagios-plugins.org/doc/guidelines.html, Performance Data Format
    Specification): space-separated `'label'=value[UOM];[warn];[crit];[min];[max]`
    tokens, the label single-quoted only when it contains a space. Returns
    `{label: {"value": float, "warn": float | None, "crit": float | None,
    "min": float | None, "max": float | None}}`.

    No exception ever escapes this function (matches this module's
    existing skip-not-fatal posture, T-09-03): a token with no `=` is
    skipped; a value that does not parse as a float skips that one token
    only; an empty or non-numeric warn/crit/min/max field becomes `None`;
    a non-string or empty `raw` returns `{}`.
    """
    if not isinstance(raw, str) or not raw:
        return {}

    def _num(parts: list[str], index: int) -> float | None:
        if index >= len(parts) or not parts[index]:
            return None
        try:
            return float(parts[index])
        except ValueError:
            return None

    result: dict[str, dict] = {}
    for token in _PERF_DATA_TOKEN_RE.findall(raw):
        if "=" not in token:
            continue
        label, _, rest = token.partition("=")
        label = label.strip("'")
        parts = rest.split(";")
        try:
            value = float(_strip_uom(parts[0]))
        except (ValueError, IndexError):
            continue
        result[label] = {
            "value": value,
            "warn": _num(parts, 1),
            "crit": _num(parts, 2),
            "min": _num(parts, 3),
            "max": _num(parts, 4),
        }
    return result


def _livestatus_request(host: str, port: int, query: str, timeout: float) -> str:
    """Send one LQL query and return the raw response body.

    Every Livestatus network failure funnels through this one choke
    point and is normalized into `LivestatusError` exactly once (same
    pattern as `CheckmkClient._request` in `src/checkmk_wizard/api.py`),
    so call sites never need their own try/except for connectivity.
    Extends `src/checkmk_wizard/livestatus.py`'s exact transport idiom;
    only the LQL headers differ.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(query.encode())
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except (TimeoutError, OSError) as exc:
        raise LivestatusError(f"Livestatus request to {host}:{port} failed: {exc}") from exc
    return b"".join(chunks).decode(errors="replace")


def cmk_rest_base_url(config: PollerConfig) -> str:
    """Build the Checkmk REST API base URL, replicating `_site_base()`'s
    construction (`src/checkmk_wizard/api.py`) without importing that
    module -- D-01 locks this script as standalone (see module docstring).
    """
    return f"http://{config.cmk_rest_host}:{config.cmk_rest_port}/{config.cmk_site_id}/check_mk/api/1.0"


def fetch_host_config(base_url: str, username: str, secret: str, timeout: float) -> dict[str, HostConfigInfo]:
    """Fetch every host's folder, map position, and unmanaged-switch marker via one REST GET.

    Every REST network failure funnels through this one choke point and
    is normalized into `RestError` exactly once, mirroring
    `_livestatus_request`'s single-choke-point pattern above. The
    RestError message names the URL and the underlying error but never
    the Authorization header, username, or secret (T-10-10).

    Live-verified against a real Checkmk 2.4.0p35 CE site on 2026-09-11
    (plan 10-01's probe, `scripts/probe_checkmk_rest_shapes.py`):
    `extensions.folder` is present on every `host_config` collection
    entry as a plain string (observed `'/folder2'`), and no
    `folder_config` link href exists anywhere in the entry's `links`
    array on this site/version -- Pattern 3 Candidate B (link-following)
    is not available, so this implements Candidate A exclusively.

    Extended 2026-09-23 (plan 13-04) to also read `extensions.attributes.labels`
    off the same collection entry -- live-verified present by 13-01's probe
    (VERDICT V-LABELS-IN-COLLECTION: YES) on the same GET, so `map_position`/
    `unmanaged` cost no additional REST call. `map_position` is accepted only
    when it matches `_MAP_POSITION_RE` (mirrors `dashboard-react/src/lib/
    topologyLayout.ts`'s `parseMapPosition()` validation exactly, T-13-11);
    an invalid or absent value degrades to `None`, never raises. `unmanaged`
    is a strict `== UNMANAGED_SWITCH_VALUE` check, never a truthy coercion.

    Extended 2026-09-26 (D-07/D-08/D-09, plan 14-07) to also read the
    `criticality`/`service_criticality`/`depends_on` labels off the same
    collection entry -- same GET, no extra REST call. Each is run through
    its own strict parser (`_parse_criticality`/`_parse_service_criticality`/
    `_parse_depends_on`), which degrades any out-of-vocabulary or malformed
    value to a safe default and never raises (T-14-19).
    """
    url = f"{base_url}/domain-types/host_config/collections/all"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {username} {secret}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise RestError(f"REST host-config lookup to {url} failed: {exc}") from exc

    result: dict[str, HostConfigInfo] = {}
    for entry in data.get("value", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        host_id = entry.get("id")
        if not host_id:
            _logger.debug("Skipping host_config entry with no id: %r", entry)
            continue
        extensions = entry.get("extensions", {})
        if not isinstance(extensions, dict):
            extensions = {}
        folder = extensions.get("folder", "")
        # `extensions.folder` (A2, live-confirmed) carries a leading slash
        # and no trailing slash (e.g. '/folder2') -- strip the leading
        # slash so downstream consumers see the same `a/b` segment shape
        # `derive_folder()` used to produce, no shape change for callers.
        folder = folder.lstrip("/") if isinstance(folder, str) else ""

        attributes = extensions.get("attributes", {})
        labels = attributes.get("labels", {}) if isinstance(attributes, dict) else {}
        if not isinstance(labels, dict):
            labels = {}

        raw_map_position = labels.get(MAP_POSITION_LABEL)
        map_position = (
            raw_map_position
            if isinstance(raw_map_position, str) and _MAP_POSITION_RE.match(raw_map_position)
            else None
        )
        unmanaged = labels.get(UNMANAGED_SWITCH_LABEL) == UNMANAGED_SWITCH_VALUE
        criticality = _parse_criticality(labels.get(CRITICALITY_LABEL))
        service_criticality = _parse_service_criticality(labels.get(SERVICE_CRITICALITY_LABEL))
        depends_on = _parse_depends_on(labels.get(DEPENDS_ON_LABEL), host_id)

        result[host_id] = HostConfigInfo(
            folder=folder,
            map_position=map_position,
            unmanaged=unmanaged,
            criticality=criticality,
            service_criticality=service_criticality,
            depends_on=depends_on,
        )
    return result


def fetch_host_folders(base_url: str, username: str, secret: str, timeout: float) -> dict[str, str]:
    """Thin folder-only wrapper over `fetch_host_config()` (D-04 legacy shape).

    Every existing caller/test of this function predates Phase 13 and only
    needs the folder mapping -- this keeps that contract byte-for-byte
    unchanged (same return type, same behavior on success and on
    `RestError`) while `fetch_host_config()` above becomes the single real
    REST call both this function and the map-position/unmanaged callers
    share, per 13-01 VERDICT V-LABELS-IN-COLLECTION (no second REST call).
    """
    return {
        host_id: info.folder
        for host_id, info in fetch_host_config(base_url, username, secret, timeout).items()
    }


def _clickhouse_request(
    url: str,
    *,
    user: str,
    password: str,
    timeout: float,
    data: bytes | None = None,
    method: str = "GET",
) -> bytes:
    """Send one HTTP request to ClickHouse and return the raw response body.

    Every ClickHouse network failure funnels through this one choke point
    and is normalized into `ClickHouseError` exactly once, mirroring
    `_livestatus_request`'s/`fetch_host_config`'s single-choke-point
    pattern above. Auth is via the `X-ClickHouse-User`/`X-ClickHouse-Key`
    headers (docs.checkmk.com is not the source here -- verified via
    context7, clickhouse.com/docs/concepts/features/interfaces/http,
    2026-09-28: the HTTP interface accepts credentials as headers so they
    never appear in the URL or in request logs, T-14.1-10). The password
    is never included in any exception message this function raises.
    """
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-ClickHouse-User": user,
            "X-ClickHouse-Key": password,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # ClickHouse's HTTP interface returns the SQL error as the response
        # body on a non-2xx status (e.g. "Table history.metrics doesn't
        # exist") -- surface up to 300 chars of it so a logged warning is
        # actionable, without risking an unbounded body in the log line.
        # A synthetic HTTPError with no underlying fp (as in some tests)
        # cannot be read; degrade to an empty body rather than raising a
        # second, unrelated exception out of this except clause.
        try:
            body = exc.read()[:300].decode(errors="replace")
        except Exception:  # noqa: BLE001 - deliberately broad, see comment above
            body = ""
        raise ClickHouseError(
            f"ClickHouse {method} to {url} failed: HTTP {exc.code}: {body}"
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ClickHouseError(f"ClickHouse {method} to {url} failed: {exc}") from exc


def _clickhouse_insert(
    base_url: str,
    user: str,
    password: str,
    table: str,
    rows: list[dict],
    timeout: float,
) -> None:
    """POST `rows` to ClickHouse as one `INSERT INTO {table} FORMAT JSONEachRow` batch.

    D-44: one INSERT per table per cycle, no buffering, no file, no retry
    -- a rejected or unreachable batch is simply dropped by the caller
    (`write_history()` below) and the gap reads as "no data" (D-47).
    `table` must be one of `CLICKHOUSE_INSERT_TABLES` (T-14.1-08): the name
    is interpolated into the SQL text since ClickHouse's HTTP interface has
    no parameterized-identifier syntax, so an unlisted table never reaches
    a request at all. An empty `rows` list is a no-op (no request made) --
    a quiet cycle (e.g. `services=None`) must not spam ClickHouse with
    empty inserts.
    """
    if not rows:
        return
    if table not in CLICKHOUSE_INSERT_TABLES:
        raise ClickHouseError(f"Refusing to insert into unlisted table {table!r}")
    try:
        body = "\n".join(json.dumps(row, allow_nan=False) for row in rows).encode("utf-8")
    except ValueError as exc:
        # allow_nan=False raises ValueError on NaN/inf -- a second guard
        # behind build_history_rows()'s own finite-value filtering
        # (T-14.1-12), never silently sending a value ClickHouse would
        # reject anyway.
        raise ClickHouseError(f"Refusing to insert non-finite value into {table}: {exc}") from exc
    url = f"{base_url}/?query=" + urllib.parse.quote(f"INSERT INTO {table} FORMAT JSONEachRow")
    _clickhouse_request(url, user=user, password=password, timeout=timeout, data=body, method="POST")


def _clickhouse_query(base_url: str, user: str, password: str, sql: str, timeout: float) -> list[dict]:
    """Run a read-only `sql` query and return its rows as a list of dicts.

    GET is used deliberately, not just by convention: ClickHouse's HTTP
    interface forces `readonly=1` on GET requests server-side (verified
    via context7, clickhouse.com/docs/concepts/features/configuration/
    settings/permissions-for-queries, 2026-09-28), so a query built from
    this function can never accidentally mutate data even if `sql` were
    malformed -- a free safety net on top of the read-only ClickHouse user
    D-54 provisions. `" FORMAT JSONEachRow"` is appended to `sql` so the
    response body is one JSON object per line. Note for callers: ClickHouse
    renders 64-bit integers (UInt64/Int64) as JSON strings by default, so a
    count column needs `int(...)` at the call site, not a bare comparison.
    """
    url = f"{base_url}/?query=" + urllib.parse.quote(f"{sql} FORMAT JSONEachRow")
    body = _clickhouse_request(url, user=user, password=password, timeout=timeout, method="GET")
    text = body.decode(errors="replace")
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ClickHouseError(f"Malformed JSONEachRow response for query {sql!r}: {exc}") from exc


def _clickhouse_command(base_url: str, user: str, password: str, sql: str, timeout: float) -> str:
    """POST `sql` as the request body and return ClickHouse's decoded text response.

    For statements that must not be sent as a GET (e.g. `INSERT INTO
    FUNCTION s3(...)`, used by plan 14.1-05's Parquet rollup export) --
    GET forces readonly=1 (see `_clickhouse_query()` above), which such
    statements would fail under. No caller exists in this plan.
    """
    url = f"{base_url}/"
    body = _clickhouse_request(
        url, user=user, password=password, timeout=timeout, data=sql.encode("utf-8"), method="POST"
    )
    return body.decode(errors="replace")


@dataclass
class HistoryBatch:
    """One poll cycle's rows, ready for `write_history()` (D-42/D-43)."""

    metrics: list[dict] = field(default_factory=list)
    host_state: list[dict] = field(default_factory=list)
    service_state: list[dict] = field(default_factory=list)


def build_history_rows(
    snapshots: list[DeviceSnapshot],
    services: list[ServiceSnapshot] | None,
    ts: datetime.datetime,
) -> HistoryBatch:
    """Turn one cycle's already-fetched snapshots/services into ClickHouse rows.

    Pure transform, never raises (matches `parse_perf_data()`'s posture
    above): garbage/absent input degrades to an empty list for that row
    kind, never an exception.

    Decisions:
    - `ts` is stamped identically on every row of the batch (one cycle,
      one timestamp) as `"YYYY-MM-DD HH:MM:SS"` in UTC -- a naive or
      non-UTC-aware `ts` is converted via `.astimezone(datetime.UTC)`
      first, so a caller passing local time still lands correctly.
    - Host rows: one per snapshot, every host (D-42's "every service"
      companion for hosts) -- `is_publishable_device_id()` gates MQTT
      topic safety, not history rows, which are keyed by plain table
      columns, so it does not apply here. `host_state_raw` is mapped
      through `HOST_STATE_CODES`; an unrecognized value (should not
      happen, `host_state_label()` only ever returns UP/DOWN/UNREACH)
      degrades to 0 (UP) rather than raising.
    - Service rows: one per `ServiceSnapshot`, every service (D-42: no
      `SERVICE_LIST_EXCLUDED_EXACT` filtering here -- that filtering is a
      dashboard display concern, not a history-recording one).
      `state_raw` outside the documented 0..3 range degrades to 3
      (UNKNOWN).
    - Metric rows: one per `perf_data` label. A label whose `value` is not
      a finite `int`/`float` (NaN, inf, a `bool`, a string, ...) is
      skipped entirely -- `math.isfinite()` on `int`/`float` only, `bool`
      explicitly excluded despite being an `int` subclass so a
      stray `True`/`False` value never becomes `1`/`0` silently. A
      non-finite `warn`/`crit` becomes `None` rather than skipping the
      whole row, since the value itself is still meaningful without
      thresholds.
    - Every row dict has exactly the contract's columns and no others (in
      particular, `plugin_output` is never carried into a row) --
      `ServiceSnapshot.plugin_output` and `DeviceSnapshot.device_type`/
      `criticality`/etc. are deliberately not read here.
    - `services=None` (services probe unavailable this cycle, D-12/D-13)
      yields empty `service_state`/`metrics` lists; `host_state` is still
      built from `snapshots`, which come from the poller's mandatory
      Livestatus query and are always available when this function runs.
    """
    stamp = ts.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")

    def _finite_or_none(raw: object) -> float | None:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return raw if math.isfinite(raw) else None

    host_rows = [
        {
            "ts": stamp,
            "host": snapshot.id,
            "folder": snapshot.folder,
            "state": HOST_STATE_CODES.get(snapshot.host_state_raw, 0),
            "in_downtime": 1 if snapshot.in_downtime else 0,
        }
        for snapshot in snapshots
    ]

    service_rows: list[dict] = []
    metric_rows: list[dict] = []
    for service in services or []:
        state_raw = service.state_raw if service.state_raw in (0, 1, 2, 3) else 3
        service_rows.append(
            {
                "ts": stamp,
                "host": service.host_name,
                "service": service.description,
                "state": state_raw,
            }
        )
        for metric, values in (service.perf_data or {}).items():
            value = _finite_or_none(values.get("value") if isinstance(values, dict) else None)
            if value is None:
                continue
            metric_rows.append(
                {
                    "ts": stamp,
                    "host": service.host_name,
                    "service": service.description,
                    "metric": metric,
                    "value": value,
                    "warn": _finite_or_none(values.get("warn")),
                    "crit": _finite_or_none(values.get("crit")),
                }
            )

    return HistoryBatch(metrics=metric_rows, host_state=host_rows, service_state=service_rows)


def write_history(config: PollerConfig, batch: HistoryBatch) -> None:
    """Push one cycle's `HistoryBatch` to ClickHouse -- never raises (D-44/D-47).

    A no-op when `config.clickhouse_url` is unset (the poller behaves
    exactly as before Phase 14.1). Otherwise each of the three tables is
    inserted in its own try/except so a failure on one (e.g. a bad metric
    row) cannot also drop the host/service state rows availability
    rollups depend on. No buffering, no retry, no file: an unreachable or
    rejecting ClickHouse simply drops that cycle's rows for that table,
    and the gap reads as "no data" downstream (D-47) rather than as up or
    down.
    """
    if not config.clickhouse_url:
        return
    for table, rows in (
        ("history.metrics", batch.metrics),
        ("history.host_state", batch.host_state),
        ("history.service_state", batch.service_state),
    ):
        try:
            _clickhouse_insert(
                config.clickhouse_url,
                config.clickhouse_writer_user,
                config.clickhouse_writer_password,
                table,
                rows,
                config.clickhouse_timeout_seconds,
            )
        except ClickHouseError as exc:
            _logger.warning(
                "ClickHouse write to %s failed this cycle; the gap reads as no data (D-44/D-47): %s",
                table,
                exc,
            )


def local_day_bounds(
    day: datetime.date, tz: zoneinfo.ZoneInfo
) -> tuple[datetime.datetime, datetime.datetime]:
    """Local midnight of `day` and of `day + 1`, both converted to UTC (D-49).

    This Python-computed boundary is the source of truth for the SQL
    window `fetch_host_day_counts()` below queries with -- never the
    container's own `TZ`, and never ClickHouse's own `toDate(ts, tz)`,
    which is only good for an independent server-side sanity check
    (research Anti-Patterns).
    """
    start_local = datetime.datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + datetime.timedelta(days=1)
    return start_local.astimezone(datetime.UTC), end_local.astimezone(datetime.UTC)


def rollup_days_to_check(
    today_local: datetime.date, first_data_day: datetime.date | None, backfill_days: int
) -> list[datetime.date]:
    """Ascending list of days eligible for a rollup: from the backfill floor up to yesterday (D-52).

    Never a day before `first_data_day` -- a pre-deployment day would
    otherwise be reported as 100% no-data -- and never `today_local`
    itself, which is still in progress. Returns `[]` when there is no
    recorded data yet (`first_data_day` is `None`) or when
    `first_data_day` is not strictly before `today_local`.
    """
    if first_data_day is None or first_data_day >= today_local:
        return []
    earliest = max(today_local - datetime.timedelta(days=backfill_days), first_data_day)
    latest = today_local - datetime.timedelta(days=1)
    if earliest > latest:
        return []
    days: list[datetime.date] = []
    current = earliest
    while current <= latest:
        days.append(current)
        current += datetime.timedelta(days=1)
    return days


def rollup_object_keys(day: datetime.date) -> tuple[str, str]:
    """Return `(json_key, parquet_key)` for `day` (D-53/D-57, Hive-style `date=` prefix)."""
    iso = day.isoformat()
    json_key = f"availability/{day:%Y}/{day:%m}/{iso}.json"
    parquet_key = f"availability_parquet/date={iso}/availability.parquet"
    return json_key, parquet_key


def _rollup_count(raw: object) -> int:
    """Coerce a sample count to a non-negative int; any unparsable value counts as 0.

    Matches this module's existing skip-not-fatal posture (`parse_perf_data`,
    `compute_incidents`): a ClickHouse row is trusted input in production,
    but a test or a schema drift should degrade, not crash the rollup.
    """
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


def compute_daily_availability(
    day: datetime.date,
    host_rows: list[dict],
    poll_interval_seconds: int,
    day_seconds: int = 86400,
) -> list[dict]:
    """Compute UP/DOWN/UNOBSERVED/downtime/no-data minutes and percentages for one day.

    Pure function, no I/O, never raises (matches `parse_perf_data()`'s
    posture): garbage/unparsable sample counts in `host_rows` degrade to 0
    via `_rollup_count()`.

    Each sample represents `poll_interval_seconds` of wall-clock time;
    `expected` minutes is always `day_seconds / 60`, regardless of how
    many samples were actually observed. `no_data = max(expected -
    observed, 0)` (D-47); the percentage base is `max(expected, observed)`
    so a day with MORE samples than expected (e.g. a brief double-poll)
    still sums to ~100% rather than exceeding it, and `no_data` never goes
    negative in that same case.

    `availability_pct = up / (up + down) * 100`, or `None` when
    `up + down == 0` -- UNREACHABLE is excluded from the denominator per
    D-45, scheduled downtime per D-46, no-data per D-47: none of the three
    ever counts as "up" or "down" for this figure.

    Known approximation: counting samples this way assumes the poll
    interval was constant for the whole day -- a mid-day
    `POLL_INTERVAL_SECONDS` change is not detectable from the stored
    samples alone.

    Rows are returned in this order: one per device (sorted by host), then
    one per folder (`group_type` "folder", `entity_key` = the folder path
    or `FOLDERLESS_GROUP_KEY` for an empty folder, figures summed across
    that folder's devices' minutes and bases, `device_count` the number of
    devices in it), then one fleet-wide row (`group_type` "fleet",
    `entity_key` `FLEET_GROUP_KEY`, always present even when `host_rows`
    is empty). The generic `group_type`/`entity_key` pair lets a future
    phase add a location group without a format change (D-48).
    """

    def _raw_figures(up_s: int, down_s: int, unreach_s: int, downtime_s: int) -> dict[str, float]:
        up = up_s * poll_interval_seconds / 60
        down = down_s * poll_interval_seconds / 60
        unobserved = unreach_s * poll_interval_seconds / 60
        downtime = downtime_s * poll_interval_seconds / 60
        observed = up + down + unobserved + downtime
        expected = day_seconds / 60
        no_data = max(expected - observed, 0.0)
        base = max(expected, observed)
        return {
            "up_minutes": up,
            "down_minutes": down,
            "unobserved_minutes": unobserved,
            "downtime_minutes": downtime,
            "no_data_minutes": no_data,
            "base": base,
        }

    def _sum_raw(raws: list[dict[str, float]]) -> dict[str, float]:
        return {
            key: sum(raw[key] for raw in raws)
            for key in (
                "up_minutes",
                "down_minutes",
                "unobserved_minutes",
                "downtime_minutes",
                "no_data_minutes",
                "base",
            )
        }

    def _round_figures(raw: dict[str, float]) -> dict[str, float | None]:
        base = raw["base"]

        def _pct(minutes: float) -> float:
            return round(minutes / base * 100, 3) if base else 0.0

        denom = raw["up_minutes"] + raw["down_minutes"]
        availability = round(raw["up_minutes"] / denom * 100, 3) if denom else None
        return {
            "up_minutes": round(raw["up_minutes"], 2),
            "down_minutes": round(raw["down_minutes"], 2),
            "unobserved_minutes": round(raw["unobserved_minutes"], 2),
            "downtime_minutes": round(raw["downtime_minutes"], 2),
            "no_data_minutes": round(raw["no_data_minutes"], 2),
            "up_pct": _pct(raw["up_minutes"]),
            "down_pct": _pct(raw["down_minutes"]),
            "unobserved_pct": _pct(raw["unobserved_minutes"]),
            "downtime_pct": _pct(raw["downtime_minutes"]),
            "no_data_pct": _pct(raw["no_data_minutes"]),
            "availability_pct": availability,
        }

    day_iso = day.isoformat()
    device_entries: list[tuple[str, str, dict[str, float]]] = []
    rows: list[dict] = []

    for host_row in sorted(host_rows, key=lambda row: str(row.get("host", ""))):
        host = str(host_row.get("host", ""))
        folder = str(host_row.get("folder") or "")
        raw = _raw_figures(
            _rollup_count(host_row.get("up_samples")),
            _rollup_count(host_row.get("down_samples")),
            _rollup_count(host_row.get("unreach_samples")),
            _rollup_count(host_row.get("downtime_samples")),
        )
        device_entries.append((host, folder, raw))
        rows.append(
            {
                "day": day_iso,
                "entity_type": "device",
                "group_type": "",
                "entity_key": host,
                "folder": folder,
                "device_count": 1,
                "schema_version": AVAILABILITY_SCHEMA_VERSION,
                **_round_figures(raw),
            }
        )

    folder_groups: dict[str, list[dict[str, float]]] = {}
    for _host, folder, raw in device_entries:
        key = folder or FOLDERLESS_GROUP_KEY
        folder_groups.setdefault(key, []).append(raw)

    for key in sorted(folder_groups):
        raws = folder_groups[key]
        rows.append(
            {
                "day": day_iso,
                "entity_type": "group",
                "group_type": "folder",
                "entity_key": key,
                "folder": key,
                "device_count": len(raws),
                "schema_version": AVAILABILITY_SCHEMA_VERSION,
                **_round_figures(_sum_raw(raws)),
            }
        )

    if device_entries:
        fleet_raws = [raw for _host, _folder, raw in device_entries]
        fleet_figures = _round_figures(_sum_raw(fleet_raws))
        fleet_device_count = len(fleet_raws)
    else:
        expected_minutes = round(day_seconds / 60, 2)
        fleet_figures = {
            "up_minutes": 0.0,
            "down_minutes": 0.0,
            "unobserved_minutes": 0.0,
            "downtime_minutes": 0.0,
            "no_data_minutes": expected_minutes,
            "up_pct": 0.0,
            "down_pct": 0.0,
            "unobserved_pct": 0.0,
            "downtime_pct": 0.0,
            "no_data_pct": 100.0,
            "availability_pct": None,
        }
        fleet_device_count = 0

    rows.append(
        {
            "day": day_iso,
            "entity_type": "group",
            "group_type": "fleet",
            "entity_key": FLEET_GROUP_KEY,
            "folder": "",
            "device_count": fleet_device_count,
            "schema_version": AVAILABILITY_SCHEMA_VERSION,
            **fleet_figures,
        }
    )

    return rows


_AVAILABILITY_FIGURE_KEYS = (
    "up_minutes",
    "down_minutes",
    "unobserved_minutes",
    "downtime_minutes",
    "no_data_minutes",
    "up_pct",
    "down_pct",
    "unobserved_pct",
    "downtime_pct",
    "no_data_pct",
    "availability_pct",
)


def availability_document(
    day: datetime.date,
    rows: list[dict],
    *,
    timezone_name: str,
    poll_interval_seconds: int,
    generated_at_iso: str,
) -> dict:
    """Build the day's JSON rollup document directly from `rows` -- never recomputed (D-53/D-57).

    A pure reshape of `compute_daily_availability()`'s own output into the
    devices/groups document shape: the JSON and the Parquet export (which
    reads these same rows back out of ClickHouse) can never drift from
    each other by construction, since neither recomputes any figure.
    """
    devices = [
        {
            "host": row.get("entity_key"),
            "folder": row.get("folder"),
            **{key: row.get(key) for key in _AVAILABILITY_FIGURE_KEYS},
        }
        for row in rows
        if row.get("entity_type") == "device"
    ]
    groups = [
        {
            "group_type": row.get("group_type"),
            "group_key": row.get("entity_key"),
            "device_count": row.get("device_count"),
            **{key: row.get(key) for key in _AVAILABILITY_FIGURE_KEYS},
        }
        for row in rows
        if row.get("entity_type") == "group"
    ]
    return {
        "schema_version": AVAILABILITY_SCHEMA_VERSION,
        "date": day.isoformat(),
        "timezone": timezone_name,
        "poll_interval_seconds": poll_interval_seconds,
        "generated_at": generated_at_iso,
        "definitions": {
            "up_pct": "Percentage of the day this entity was reachable and OK (D-45).",
            "down_pct": "Percentage of the day this entity was confirmed DOWN (D-45).",
            "unobserved_pct": (
                "Percentage of the day this entity was UNREACHABLE; excluded from "
                "availability as not observable (D-45)."
            ),
            "downtime_pct": (
                "Percentage of the day this entity was in scheduled downtime; "
                "excluded from availability (D-46)."
            ),
            "no_data_pct": (
                "Percentage of the day with no poller data; excluded from "
                "availability (D-47)."
            ),
            "availability_pct": (
                "up / (up + down) * 100; null when neither was observed this day (D-45)."
            ),
        },
        "devices": devices,
        "groups": groups,
    }


def availability_document_problems(doc: dict) -> list[str]:
    """Human-readable problems with `doc`, project convention (like `_password_problems`).

    Returns `[]` when `doc` is well-formed. Never raises: a malformed
    `doc` (wrong types, missing keys) degrades to a problem message
    naming the issue rather than a traceback, since this gate runs
    immediately before a JSON PUT (`rollup_one_day()` below) and must
    always be able to explain a refusal.
    """
    problems: list[str] = []
    if doc.get("schema_version") != AVAILABILITY_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {AVAILABILITY_SCHEMA_VERSION}, got {doc.get('schema_version')!r}"
        )
    try:
        datetime.date.fromisoformat(str(doc.get("date")))
    except (TypeError, ValueError):
        problems.append(f"date {doc.get('date')!r} is not a valid ISO date")

    devices = doc.get("devices")
    if not isinstance(devices, list):
        problems.append("devices must be a list")
        devices = []
    groups = doc.get("groups")
    if not isinstance(groups, list):
        problems.append("groups must be a list")
        groups = []

    def _check_numeric(entry: dict, label: str, key: str, *, allow_none: bool) -> None:
        value = entry.get(key)
        if value is None and allow_none:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{label} {key} is not numeric: {value!r}")
        elif not (0 <= value <= 100.001):
            problems.append(f"{label} {key} is out of range 0..100: {value!r}")

    def _check_entry(entry: object, label: str) -> None:
        if not isinstance(entry, dict):
            problems.append(f"{label} entry is not an object: {entry!r}")
            return
        for key in (
            "up_pct",
            "down_pct",
            "unobserved_pct",
            "downtime_pct",
            "no_data_pct",
        ):
            _check_numeric(entry, label, key, allow_none=False)
        _check_numeric(entry, label, "availability_pct", allow_none=True)

    for entry in devices:
        _check_entry(entry, "device")
    for entry in groups:
        _check_entry(entry, "group")

    return problems


class RollupError(RuntimeError):
    """Raised when the availability rollup for a day cannot be safely written.

    Caught at `run_rollups()`'s per-day call site and logged -- never
    allowed to abort the rest of the backfill window or the poll loop
    (D-44).
    """


def build_s3_client(config: PollerConfig):
    """Build a `boto3` S3 client from `config`'s `S3_*` settings (D-41).

    Plain S3 API only -- no MinIO-specific calls anywhere in this module.
    Portable to AWS S3 by configuration alone: point `S3_ENDPOINT` at the
    regional AWS endpoint (or leave it unset and let boto3 resolve AWS's
    own default), set `S3_REGION`, and switch `S3_ADDRESSING_STYLE` to
    "virtual" -- no code change is needed (D-41).
    """
    return boto3.client(
        "s3",
        endpoint_url=config.s3_endpoint,
        aws_access_key_id=config.s3_access_key,
        aws_secret_access_key=config.s3_secret_key,
        region_name=config.s3_region,
        config=botocore.config.Config(
            signature_version="s3v4",
            s3={"addressing_style": config.s3_addressing_style},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def object_exists(s3, bucket: str, key: str) -> bool:
    """True if `key` exists in `bucket`, checked via HEAD (never a GET, no body transfer)."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def write_if_absent(s3, bucket: str, key: str, payload: bytes, content_type: str) -> bool:
    """HEAD-before-PUT: write `payload` to `key` only if it does not already exist (D-52/D-57).

    HEAD-before-PUT, not a conditional PUT (`If-None-Match`): MinIO's
    support for the wildcard conditional-write semantic is
    version-dependent (research Pitfall 2), while HEAD-before-PUT works
    identically on every S3-compatible backend. The narrow TOCTOU window
    this leaves is accepted -- the rollup job is a single writer, running
    at most once per day per object.
    """
    if object_exists(s3, bucket, key):
        return False
    s3.put_object(Bucket=bucket, Key=key, Body=payload, ContentType=content_type)
    return True


# Phase 14.1: the rollup timezone name is interpolated directly into SQL
# (`fetch_first_data_day()` below has no parameterized-identifier syntax to
# fall back on, the same constraint `_clickhouse_insert`'s table allowlist
# works around for table names) -- reject anything that is not
# letters/underscores/hyphens/pluses separated by slashes before it ever
# reaches a query.
_TZ_NAME_RE = re.compile(r"^[A-Za-z_]+(/[A-Za-z_+-]+)*$")


def _validate_tz_name(name: str) -> str:
    """Return `name` unchanged if it looks like a safe IANA zone name, else raise `RollupError`."""
    if not _TZ_NAME_RE.match(name or ""):
        raise RollupError(f"Refusing to use unsafe timezone name in SQL: {name!r}")
    return name


def fetch_first_data_day(config: PollerConfig, tz_name: str) -> datetime.date | None:
    """Return the earliest local calendar day with any `history.host_state` row, or `None` if empty.

    Bounds D-52's backfill window from below: never roll up a day before
    the fleet actually had data, which would otherwise report a
    pre-deployment day as 100% no-data. `tz_name` must already be
    validated by the caller (`run_rollups()`) since it is interpolated
    into this query's SQL text.
    """
    rows = _clickhouse_query(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        f"SELECT toString(toDate(min(ts), '{tz_name}')) AS d, count() AS n FROM history.host_state",
        config.clickhouse_timeout_seconds,
    )
    if not rows or int(rows[0].get("n", 0)) == 0:
        return None
    return datetime.date.fromisoformat(rows[0]["d"])


def fetch_host_day_counts(
    config: PollerConfig, start_utc: datetime.datetime, end_utc: datetime.datetime
) -> list[dict]:
    """Per-host up/down/unreach/downtime sample counts for `[start_utc, end_utc)` (D-51).

    Computed fresh from ClickHouse's durable `history.host_state` table on
    every call -- never from in-memory poller counters -- so a poller
    restart mid-day cannot lose or corrupt that day's figures.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "SELECT host, argMax(folder, ts) AS folder, "
        "sumIf(samples, state = 0 AND in_downtime = 0) AS up_samples, "
        "sumIf(samples, state = 1 AND in_downtime = 0) AS down_samples, "
        "sumIf(samples, state = 2 AND in_downtime = 0) AS unreach_samples, "
        "sumIf(samples, in_downtime = 1) AS downtime_samples "
        "FROM history.host_state "
        f"WHERE ts >= toDateTime('{start_str}', 'UTC') AND ts < toDateTime('{end_str}', 'UTC') "
        "GROUP BY host ORDER BY host"
    )
    return _clickhouse_query(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        sql,
        config.clickhouse_timeout_seconds,
    )


# Phase 14.1 (D-57): a single quote or backslash in an S3 credential would
# break out of the SQL string literal `export_parquet()` builds below --
# ClickHouse's `s3()` table function has no parameterized-credential form,
# so this is the same defense-before-interpolation posture as
# `_TZ_NAME_RE` above.
_SQL_UNSAFE_CREDENTIAL_RE = re.compile(r"['\\]")


def export_parquet(config: PollerConfig, day: datetime.date, parquet_key: str) -> None:
    """Export `day`'s already-inserted `history.availability_daily` rows to Parquet (D-57).

    ClickHouse writes the Parquet directly from the rows the poller just
    inserted into `history.availability_daily`, so the JSON (written from
    that same in-memory row list by `rollup_one_day()`) and this Parquet
    twin carry identical figures by construction -- never a second,
    independently-computed pass that could drift (research Anti-Patterns).

    Refuses (`ClickHouseError`, no request sent) if the S3 access key or
    secret contains a single quote or backslash, since both are
    interpolated directly into the SQL statement's string literals. By
    default ClickHouse refuses to overwrite an existing `s3()` object
    (`s3_truncate_on_insert` is never set here) -- a second never-overwrite
    layer behind `write_if_absent()`'s own `object_exists()` check.
    Verified via context7 (clickhouse/clickhouse-docs,
    docs/sql-reference/table-functions/s3.md: `INSERT INTO FUNCTION
    s3(...)` fails on an existing key unless `s3_truncate_on_insert=1` is
    set) and that `s3()` credentials are masked in ClickHouse's own query
    logs (clickhouse/clickhouse-docs, docs/operations/server-configuration-
    parameters/settings.md `query_masking_rules`: the server's built-in
    default masking rules redact S3 URL credentials before they reach any
    log). This poller never logs the credentials either.
    """
    if _SQL_UNSAFE_CREDENTIAL_RE.search(config.s3_access_key) or _SQL_UNSAFE_CREDENTIAL_RE.search(
        config.s3_secret_key
    ):
        raise ClickHouseError("Refusing Parquet export: S3 credential contains an unsafe character")
    s3_url = f"{config.s3_endpoint}/{config.availability_bucket}/{parquet_key}"
    sql = (
        f"INSERT INTO FUNCTION s3('{s3_url}', '{config.s3_access_key}', '{config.s3_secret_key}', "
        "'Parquet') "
        "SELECT day, entity_type, group_type, entity_key, folder, device_count, "
        "up_minutes, down_minutes, unobserved_minutes, downtime_minutes, no_data_minutes, "
        "up_pct, down_pct, unobserved_pct, downtime_pct, no_data_pct, availability_pct, "
        "schema_version, generated_at "
        "FROM history.availability_daily FINAL "
        f"WHERE day = toDate('{day.isoformat()}') "
        "ORDER BY entity_type, group_type, entity_key"
    )
    _clickhouse_command(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        sql,
        config.clickhouse_timeout_seconds,
    )


def rollup_one_day(config: PollerConfig, s3, tz: zoneinfo.ZoneInfo, day: datetime.date) -> str:
    """Compute and write one day's availability rollup if either object is missing (D-52/D-57).

    Returns "skipped" when both the JSON and Parquet objects already
    exist (never overwrite). Otherwise fetches this day's counts from
    ClickHouse, computes the figures, inserts them into
    `history.availability_daily`, exports the Parquet twin if missing,
    then writes the JSON if missing, and returns "written". A day left
    half-written by a prior run (only one of the two objects exists) is
    completed here -- the existing object is never touched again.
    """
    json_key, parquet_key = rollup_object_keys(day)
    json_exists = object_exists(s3, config.availability_bucket, json_key)
    parquet_exists = object_exists(s3, config.availability_bucket, parquet_key)
    if json_exists and parquet_exists:
        return "skipped"

    start_utc, end_utc = local_day_bounds(day, tz)
    host_rows = fetch_host_day_counts(config, start_utc, end_utc)
    rows = compute_daily_availability(
        day, host_rows, config.poll_interval_seconds, int((end_utc - start_utc).total_seconds())
    )

    generated_at = datetime.datetime.now(datetime.UTC)
    generated_at_str = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    _clickhouse_insert(
        config.clickhouse_url,
        config.clickhouse_writer_user,
        config.clickhouse_writer_password,
        "history.availability_daily",
        [{**row, "generated_at": generated_at_str} for row in rows],
        config.clickhouse_timeout_seconds,
    )

    if not parquet_exists:
        export_parquet(config, day, parquet_key)

    if not json_exists:
        doc = availability_document(
            day,
            rows,
            timezone_name=str(tz),
            poll_interval_seconds=config.poll_interval_seconds,
            generated_at_iso=generated_at.isoformat(),
        )
        problems = availability_document_problems(doc)
        if problems:
            raise RollupError(
                f"Refusing to write availability document for {day}: {'; '.join(problems)}"
            )
        write_if_absent(
            s3,
            config.availability_bucket,
            json_key,
            json.dumps(doc).encode("utf-8"),
            "application/json",
        )

    return "written"


def run_rollups(
    config: PollerConfig, s3, today_local: datetime.date
) -> tuple[list[datetime.date], int]:
    """Roll up every missing day back to the backfill floor, oldest first (D-52).

    A day whose rollup raises is logged and skipped -- one bad day never
    blocks the rest of the backfill window. A failure resolving the
    fleet's first recorded day propagates to the caller
    (`maybe_run_rollups()` below): without it there is no way to know
    which days are even eligible.
    """
    tz_name = _validate_tz_name(config.rollup_tz)
    tz = zoneinfo.ZoneInfo(tz_name)
    first_data_day = fetch_first_data_day(config, tz_name)
    written: list[datetime.date] = []
    failures = 0
    for day in rollup_days_to_check(today_local, first_data_day, config.rollup_backfill_days):
        try:
            result = rollup_one_day(config, s3, tz, day)
        except (
            ClickHouseError,
            RollupError,
            botocore.exceptions.BotoCoreError,
            botocore.exceptions.ClientError,
        ) as exc:
            _logger.warning("Availability rollup for %s failed; will retry later: %s", day, exc)
            failures += 1
            continue
        if result == "written":
            written.append(day)
            _logger.info("Availability rollup written for %s (JSON + Parquet)", day)
    return written, failures


@dataclass
class RollupScheduler:
    """Tracks when the next availability-rollup attempt is due (D-49/D-51/D-52).

    In-memory only -- a poller restart simply re-evaluates `due()` as
    freshly due again, which is safe because every object write below it
    is never-overwrite (D-44/D-52): a restart mid-backfill just repeats
    the days that already succeeded as no-ops.
    """

    last_completed_local_date: datetime.date | None = None
    next_attempt_monotonic: float = 0.0
    delay_minutes: int = DEFAULT_ROLLUP_DELAY_MINUTES

    def due(self, now_local: datetime.datetime, now_monotonic: float) -> bool:
        if now_monotonic < self.next_attempt_monotonic:
            return False
        if self.last_completed_local_date is None:
            return True
        if now_local.date() == self.last_completed_local_date:
            return False
        return now_local.time() >= datetime.time(0, self.delay_minutes)

    def mark_success(self, local_date: datetime.date) -> None:
        self.last_completed_local_date = local_date
        self.next_attempt_monotonic = 0.0

    def mark_failure(self, now_monotonic: float) -> None:
        self.next_attempt_monotonic = now_monotonic + ROLLUP_RETRY_SECONDS


def maybe_run_rollups(
    config: PollerConfig,
    scheduler: RollupScheduler,
    s3_holder: dict,
    tz: zoneinfo.ZoneInfo,
    now_local: datetime.datetime,
    now_monotonic: float,
) -> None:
    """Run the availability-rollup backfill once it is due, never letting a failure reach the poll loop.

    A no-op (no S3 client built, no ClickHouse query) until both
    `clickhouse_url` and `s3_endpoint` are configured -- mirrors
    `write_history()`'s "unset means disabled" posture. The one
    deliberate broad `except Exception` here matches the REST
    folder-lookup's never-fatal posture (D-44): the rollup job is
    enrichment, and no failure in it -- expected
    (`ClickHouseError`/`RollupError`/`botocore`) or not -- may ever crash
    the poller.
    """
    if not config.clickhouse_url or not config.s3_endpoint:
        return
    if not scheduler.due(now_local, now_monotonic):
        return
    try:
        if "client" not in s3_holder:
            s3_holder["client"] = build_s3_client(config)
        _written, failures = run_rollups(config, s3_holder["client"], now_local.date())
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring above
        _logger.warning(
            "Availability rollup run failed; retrying in %ss: %s", ROLLUP_RETRY_SECONDS, exc
        )
        scheduler.mark_failure(now_monotonic)
        return
    if failures == 0:
        scheduler.mark_success(now_local.date())
    else:
        scheduler.mark_failure(now_monotonic)


def available_host_columns(host: str, port: int, timeout: float) -> set[str]:
    """Return the column names the live site's `hosts` table actually exposes.

    Checkmk publishes no static column reference for the `hosts` table;
    the documented way to get ground truth is a live `GET columns` query
    (docs.checkmk.com/latest/en/livestatus_references.html) — resolves
    09-RESEARCH.md Open Question 1 / Assumptions A1-A3.
    """
    query = "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    body = _livestatus_request(host, port, query, timeout)
    if not body.strip():
        return set()
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed columns response from {host}:{port}: {exc}") from exc
    return {row[0] for row in rows}


def select_host_columns(available: set[str]) -> list[str]:
    """Build the column list to request, degrading unverified optional columns gracefully.

    Every name in REQUIRED_HOST_COLUMNS must be present or the query
    cannot proceed at all. Optional columns (parents/tags/filename etc.)
    are included only when the live site actually exposes them; an
    absent optional column is a logged degradation, not a hard failure.
    """
    missing = [name for name in REQUIRED_HOST_COLUMNS if name not in available]
    if missing:
        raise LivestatusError(
            f"Livestatus hosts table is missing required column(s): {', '.join(missing)}"
        )
    columns = list(REQUIRED_HOST_COLUMNS)
    for name in OPTIONAL_HOST_COLUMNS:
        if name in available:
            columns.append(name)
        else:
            _logger.warning(
                "Livestatus hosts table does not expose optional column %r; "
                "degrading to a safe default for that field",
                name,
            )
    return columns


def build_hosts_query(columns: list[str]) -> str:
    return f"GET hosts\nColumns: {' '.join(columns)}\nOutputFormat: json\n\n"


def available_service_columns(host: str, port: int, timeout: float) -> set[str]:
    """Return the column names the live site's `services` table actually exposes.

    Literal parallel of `available_host_columns()` above, filtered to
    `table = services` instead of `table = hosts` -- same choke point
    (`_livestatus_request`), same malformed-response handling.
    """
    query = "GET columns\nColumns: name\nFilter: table = services\nOutputFormat: json\n\n"
    body = _livestatus_request(host, port, query, timeout)
    if not body.strip():
        return set()
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed columns response from {host}:{port}: {exc}") from exc
    return {row[0] for row in rows}


def select_service_columns(available: set[str]) -> list[str]:
    """Build the services column list to request, degrading unverified optional columns gracefully.

    Literal parallel of `select_host_columns()` above: every name in
    REQUIRED_SERVICE_COLUMNS must be present or the query cannot proceed at
    all. `plugin_output`/`perf_data` are included only when the live site
    actually exposes them; an absent optional column is a logged
    degradation, not a hard failure (12-RESEARCH.md Pitfall 4).
    """
    missing = [name for name in REQUIRED_SERVICE_COLUMNS if name not in available]
    if missing:
        raise LivestatusError(
            f"Livestatus services table is missing required column(s): {', '.join(missing)}"
        )
    columns = list(REQUIRED_SERVICE_COLUMNS)
    for name in OPTIONAL_SERVICE_COLUMNS:
        if name in available:
            columns.append(name)
        else:
            _logger.warning(
                "Livestatus services table does not expose optional column %r; "
                "degrading to a safe default for that field",
                name,
            )
    return columns


def build_services_query(columns: list[str]) -> str:
    return f"GET services\nColumns: {' '.join(columns)}\nOutputFormat: json\n\n"


def query_devices(
    host: str,
    port: int,
    columns: list[str],
    timeout: float,
    *,
    folders: dict[str, str] | None = None,
    host_config: dict[str, HostConfigInfo] | None = None,
) -> list[DeviceSnapshot]:
    """Run one `GET hosts` round trip and parse it into typed DeviceSnapshot records.

    Defensive by design (T-09-03): a malformed response, a topic-unsafe
    host name, or a non-numeric state field skips that one row (or the
    whole cycle, for a fully malformed response) rather than crashing
    the poll loop.

    `folders` is the REST-sourced host-name -> folder mapping fetched
    once per cycle by `fetch_host_folders()` (D-04); a host missing from
    the mapping (or a `None` mapping, e.g. a cycle whose REST fetch never
    succeeded) degrades to folder `""` rather than raising. Kept working
    exactly as before Phase 13.

    `host_config` (Phase 13, plan 13-04) is the richer REST-sourced
    host-name -> `HostConfigInfo` mapping fetched once per cycle by
    `fetch_host_config()`; a host missing from it (or a `None` mapping)
    degrades `map_position`/`unmanaged` to their `DeviceSnapshot` defaults
    (`None`/`False`), same graceful-degradation posture as `folders`.
    Extended 2026-09-26 (D-07/D-08/D-09, plan 14-07) to also carry
    `criticality`/`depends_on`/`service_criticality` from the same
    `HostConfigInfo`, degrading the same way when the host is missing from
    `host_config`.
    """
    body = _livestatus_request(host, port, build_hosts_query(columns), timeout)
    if not body.strip():
        return []
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed hosts response from {host}:{port}: {exc}") from exc

    index = {name: position for position, name in enumerate(columns)}
    snapshots: list[DeviceSnapshot] = []
    for row in rows:
        try:
            name = row[index["name"]]
        except (IndexError, TypeError):
            _logger.warning("Skipping malformed hosts row: %r", row)
            continue
        if not is_publishable_device_id(name):
            _logger.warning("Skipping host %r: not publishable as an MQTT topic segment", name)
            continue
        try:
            host_state = int(row[index["state"]])
        except (IndexError, TypeError, ValueError):
            _logger.warning("Skipping host %r: non-numeric state", name)
            continue

        worst_service_state = 0
        if "worst_service_state" in index:
            try:
                worst_service_state = int(row[index["worst_service_state"]])
            except (IndexError, TypeError, ValueError):
                _logger.warning("Skipping host %r: non-numeric worst_service_state", name)
                continue

        downtime_depth = 0
        if "scheduled_downtime_depth" in index:
            try:
                downtime_depth = int(row[index["scheduled_downtime_depth"]])
            except (IndexError, TypeError, ValueError):
                downtime_depth = 0

        try:
            acknowledged = bool(row[index["acknowledged"]]) if "acknowledged" in index else False
        except (IndexError, TypeError):
            acknowledged = False

        try:
            raw_parents = row[index["parents"]] if "parents" in index else None
        except (IndexError, TypeError):
            raw_parents = None
        parents = list(raw_parents) if isinstance(raw_parents, list) else []

        try:
            raw_tags = row[index["tags"]] if "tags" in index else None
        except (IndexError, TypeError):
            raw_tags = None
        tags = raw_tags if isinstance(raw_tags, dict) else {}

        folder = folders.get(name, "") if folders else ""

        host_info = host_config.get(name) if host_config else None
        map_position = host_info.map_position if host_info else None
        unmanaged = host_info.unmanaged if host_info else False
        criticality = host_info.criticality if host_info else DEFAULT_CRITICALITY
        depends_on = list(host_info.depends_on) if host_info else []
        service_criticality = dict(host_info.service_criticality) if host_info else {}

        try:
            alias = row[index["alias"]] if "alias" in index else ""
        except (IndexError, TypeError):
            alias = ""
        if not isinstance(alias, str):
            alias = ""

        try:
            address = row[index["address"]] if "address" in index else ""
        except (IndexError, TypeError):
            address = ""
        if not isinstance(address, str):
            address = ""
        address = address.strip()

        try:
            staleness = float(row[index["staleness"]]) if "staleness" in index else None
        except (IndexError, TypeError, ValueError):
            staleness = None

        try:
            last_state_change = (
                int(row[index["last_state_change"]]) if "last_state_change" in index else None
            )
        except (IndexError, TypeError, ValueError):
            last_state_change = None
        if last_state_change is not None and last_state_change <= 0:
            last_state_change = None

        # Not a new column -- derived from the `host_state` int already
        # parsed above, following the same 1=DOWN/2=UNREACHABLE mapping.
        host_state_raw = host_state_label(host_state)

        snapshots.append(
            DeviceSnapshot(
                id=name,
                state=compute_overall_state(host_state, worst_service_state),
                in_downtime=downtime_depth > 0,
                acknowledged=acknowledged,
                device_type=extract_device_type(tags),
                folder=folder,
                parents=parents,
                alias=alias,
                address=address,
                staleness=staleness,
                host_state_raw=host_state_raw,
                map_position=map_position,
                unmanaged=unmanaged,
                last_state_change=last_state_change,
                criticality=criticality,
                depends_on=depends_on,
                service_criticality=service_criticality,
            )
        )
    return snapshots


def query_services(
    host: str, port: int, columns: list[str], timeout: float
) -> list[ServiceSnapshot]:
    """Run one `GET services` round trip and parse it into typed ServiceSnapshot records.

    Defensive by design (T-09-03), same skip-this-row-not-the-cycle
    posture as `query_devices()` above: a malformed row, a host name that
    could not be addressed as an MQTT topic segment, or a non-numeric
    state skips that one row rather than crashing the poll loop; a
    missing/non-string `plugin_output` or `perf_data` degrades to `""`/
    `{}` rather than raising (T-12-01/T-12-02).
    """
    body = _livestatus_request(host, port, build_services_query(columns), timeout)
    if not body.strip():
        return []
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed services response from {host}:{port}: {exc}") from exc

    index = {name: position for position, name in enumerate(columns)}
    snapshots: list[ServiceSnapshot] = []
    for row in rows:
        try:
            host_name = row[index["host_name"]]
        except (IndexError, TypeError):
            _logger.warning("Skipping malformed services row: %r", row)
            continue
        if not is_publishable_device_id(host_name):
            _logger.warning(
                "Skipping service row for host %r: not publishable as an MQTT topic segment",
                host_name,
            )
            continue
        try:
            description = row[index["description"]]
        except (IndexError, TypeError):
            _logger.warning("Skipping malformed services row: %r", row)
            continue
        try:
            state_raw = int(row[index["state"]])
        except (IndexError, TypeError, ValueError):
            _logger.warning(
                "Skipping service %r on host %r: non-numeric state", description, host_name
            )
            continue

        try:
            plugin_output = row[index["plugin_output"]] if "plugin_output" in index else ""
        except (IndexError, TypeError):
            plugin_output = ""
        if not isinstance(plugin_output, str):
            plugin_output = ""

        try:
            raw_perf_data = row[index["perf_data"]] if "perf_data" in index else ""
        except (IndexError, TypeError):
            raw_perf_data = ""
        perf_data = parse_perf_data(raw_perf_data) if isinstance(raw_perf_data, str) else {}

        snapshots.append(
            ServiceSnapshot(
                host_name=host_name,
                description=description,
                state=_SERVICE_STATE_NAMES.get(state_raw, "UNKNOWN"),
                state_raw=state_raw,
                plugin_output=plugin_output,
                perf_data=perf_data,
            )
        )
    return snapshots


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601, matching wizard.py's `datetime.UTC` convention."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def build_mqtt_client(
    config: PollerConfig, admin_worker: AdminCommandWorker | None = None
) -> mqtt.Client:
    """Construct, authenticate and connect the poller's long-lived MQTT client.

    Configuring the LWT happens before connecting because paho-mqtt's
    own docstring states it has no effect otherwise -- this ordering is
    load-bearing, not stylistic. Reconnect/backoff is deliberately left
    to the library (`reconnect_delay_set` + `loop_start`), not
    hand-rolled, per RESEARCH.md's "Don't Hand-Roll" guidance. This is
    the only client in the module configured with a will; the
    short-lived `reconcile_state` client deliberately has none (T-09-06).
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
    client.will_set(
        site_topic(TOPIC_POLLER_STATUS),
        payload=json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    def on_connect(client, userdata, flags, reason_code, properties=None):
        # Birth message: last_poll is None until the first cycle completes.
        publish_poller_status(client, since=utc_now_iso(), last_poll=None, device_count=0)
        if admin_worker is not None:
            # Subscribe on every connect: a clean-session reconnect loses subscriptions.
            client.subscribe(site_topic(TOPIC_ADMIN_CMD), qos=1)

    client.on_connect = on_connect
    if admin_worker is not None:
        admin_worker.attach_client(client)

        def on_message(client, userdata, msg):
            if msg.topic == site_topic(TOPIC_ADMIN_CMD):
                admin_worker.submit(msg.payload, msg.retain)

        client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
    client.loop_start()
    return client


def _publish_json(client: mqtt.Client, topic: str, payload: object, qos: int, retain: bool) -> None:
    """Serialize `payload` as JSON and publish, one choke point for every publish helper.

    Mirrors `CheckmkClient._request()`'s pattern (src/checkmk_wizard/api.py):
    every publish goes through here so a transient broker hiccup
    (`TimeoutError`/`OSError`) degrades exactly one publish rather than
    killing the poll loop (T-09-03).

    Continuous vs. change-triggered QoS rule (RESEARCH.md's resolved
    table): the every-cycle status topic uses QoS 0 (self-correcting by
    the next cycle), every change-triggered topic uses QoS 1. Callers
    choose `qos`; this function does not second-guess it.
    """
    try:
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)


def publish_device_status(
    client: mqtt.Client,
    snapshot: DeviceSnapshot,
    timestamp: str,
    gauge_fields: dict | None = None,
) -> None:
    """Publish one device's current status. QoS 0: republished every cycle from live data."""
    payload = {
        "id": snapshot.id,
        "state": snapshot.state,
        "in_downtime": snapshot.in_downtime,
        "acknowledged": snapshot.acknowledged,
        "device_type": snapshot.device_type,
        "folder": snapshot.folder,
        "alias": snapshot.alias,
        # Added 2026-09-28 (quick 260928-m6f): additive key, same spirit as
        # the dated D-17 comment below -- an older subscriber never sees it.
        "address": snapshot.address,
        # D-17: additive keys. An older subscriber reading a payload from
        # before this plan is unaffected -- it simply never sees these.
        "staleness": snapshot.staleness,
        "host_state_raw": snapshot.host_state_raw,
        "timestamp": timestamp,
    }
    # Phase 12 (D-12): additive gauge keys (cpu/ram/disk/smart), in the same
    # spirit as the dated D-17 staleness/host_state_raw comment above -- an
    # older subscriber simply never sees these. `None` (a services-query
    # failure this cycle) keeps the status topic publishing without gauge
    # keys rather than publishing wrong `null`s over a good retained value.
    payload.update(gauge_fields or {})
    _publish_json(client, device_status_topic(snapshot.id), payload, qos=0, retain=True)


def publish_topology(client: mqtt.Client, nodes: list[dict], timestamp: str) -> None:
    """Publish the full device topology. QoS 1: only republished when it actually changes."""
    payload = {"devices": nodes, "timestamp": timestamp}
    _publish_json(client, site_topic(TOPIC_TOPOLOGY), payload, qos=1, retain=True)


def publish_services(client: mqtt.Client, device_id: str, rows: list[dict]) -> None:
    """Publish one device's per-service row list. QoS 1: change-triggered (D-12/D-13), not
    republished every cycle -- the caller only calls this when `services_signature` differs
    from the previously published signature.
    """
    _publish_json(client, device_services_topic(device_id), rows, qos=1, retain=True)


def publish_events(client: mqtt.Client, entries: list[dict]) -> None:
    """Publish the full bounded global events feed (already truncated by the caller)."""
    _publish_json(client, site_topic(TOPIC_EVENTS), entries, qos=1, retain=True)


def publish_raw_tombstone(client: mqtt.Client, full_topic: str) -> None:
    """Clear one of this site's retired history/service_history retained topics.

    Takes the full, already-final topic string (quick 261004-kbt: the poller no
    longer publishes per-device history/service_history, ClickHouse holds
    transition history; already-retained ones are cleared once). Refuses every
    other topic so the sweep can never clear live data. The pre-14.3
    un-namespaced use of this function, and the poller's `lan/#` and `admin/#`
    ACL grants it relied on, were removed 2026-10-04 (quick 261004-lyz).
    """
    rel = relative_topic(full_topic)
    rel_parts = rel.split("/") if rel is not None else []
    retired_history = (
        len(rel_parts) == 4
        and rel_parts[:2] == ["lan", "devices"]
        and rel_parts[3] in ("history", "service_history")
    )
    if not retired_history:
        _logger.warning("Refusing to tombstone topic %s", full_topic)
        return
    try:
        info = client.publish(full_topic, payload=None, retain=True, qos=1)
        info.wait_for_publish(timeout=5)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish tombstone to %s: %s", full_topic, exc)


def publish_tombstone(client: mqtt.Client, device_id: str) -> None:
    """Clear a removed device's retained status and services topics (plus the retired
    history and service_history topics, for one release).

    A zero-length retained payload is MQTT's own defined "clear this
    retained topic" semantic -- the same mechanism as
    `scripts/smoke_test_broker.py::_cleanup`, already proven against the
    real deployed broker. Uses `wait_for_publish` like that function does,
    since a tombstone matters more than most publishes: the removed
    device must not linger as a stale retained message.

    Phase 12 (T-12-04/PLR-06): extended from two topics to four so a
    removed host leaves no ghost retained message on `services` or
    `service_history` either.
    """
    for topic in (
        device_status_topic(device_id),
        device_services_topic(device_id),
        # legacy since 2026-10-04 (quick 261004-kbt): no longer published; tombstoned for
        # one release so hosts removed right after the upgrade leave no retained ghost;
        # drop later.
        site_topic(f"lan/devices/{device_id}/history"),
        site_topic(f"lan/devices/{device_id}/service_history"),
    ):
        try:
            info = client.publish(topic, payload=None, retain=True, qos=1)
            info.wait_for_publish(timeout=5)
        except (TimeoutError, OSError) as exc:
            _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)


def publish_incident(client: mqtt.Client, incident: dict, timestamp: str) -> None:
    """Publish one incident's current state. QoS 1: change-triggered (D-13/PLR-14), the
    caller only calls this when `incident_signature()` differs from the previously
    published signature -- not republished every cycle like `publish_device_status`.
    """
    payload = {**incident, "timestamp": timestamp}
    _publish_json(client, incident_status_topic(incident["id"]), payload, qos=1, retain=True)


def publish_incident_tombstone(client: mqtt.Client, incident_id: str) -> None:
    """Clear a closed incident's retained status topic.

    Same tombstone contract as `publish_tombstone()` above (a zero-length
    retained payload is MQTT's own defined "clear this retained topic"
    semantic), applied to the single per-incident topic instead of the four
    per-device ones.
    """
    topic = incident_status_topic(incident_id)
    try:
        info = client.publish(topic, payload=None, retain=True, qos=1)
        info.wait_for_publish(timeout=5)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)


def publish_poller_status(
    client: mqtt.Client, since: str, last_poll: str | None, device_count: int
) -> None:
    """Publish the poller's liveness status: birth (`last_poll=None`) or a per-cycle heartbeat.

    MQTT's LWT only fires on an ungraceful TCP disconnect, so a poller
    whose poll loop has stalled while its network thread keeps the
    socket alive would otherwise read as permanently "online" forever.
    The refreshed `last_poll` published every cycle is what lets Phase
    11's DASH-04 staleness check ("now - last_poll > threshold") catch
    that condition (RESEARCH.md Pitfall C).
    """
    payload = {
        "status": "online",
        "since": since,
        "last_poll": last_poll,
        "device_count": device_count,
    }
    _publish_json(client, site_topic(TOPIC_POLLER_STATUS), payload, qos=1, retain=True)


def shutdown_mqtt_client(client: mqtt.Client) -> None:
    """Stop `client` gracefully while still leaving the same retained value the LWT would.

    A graceful `client.disconnect()` sends an MQTT DISCONNECT packet, which
    per spec makes the broker discard the client's Will Message -- so the
    LWT's `{"status": "offline"}` never fires on this path. Every exit path
    (fatal startup failure, `--once` completion or failure, and normal
    shutdown) must call this instead of a bare `loop_stop()`/`disconnect()`
    pair so the retained `lan/poller/status` topic reflects reality
    regardless of how the process is stopped (CR-02).
    """
    _publish_json(
        client, site_topic(TOPIC_POLLER_STATUS), {"status": "offline"}, qos=1, retain=True
    )
    client.loop_stop()
    client.disconnect()


@dataclass
class PollerState:
    """In-process poll-cycle state. Never persisted -- rebuilt via `reconcile_state` on restart."""

    previous_nodes: dict[str, dict]
    last_status: dict[str, str]
    events: list[dict]
    since: str
    # Phase 12 (D-13). `previous_services` (device id -> last published
    # `services_signature`) is deliberately NOT reconciled from a retained
    # topic on restart -- it lives only in memory and rebuilds from live
    # Livestatus every cycle, the same argument the `last_status` comment in
    # `run_cycle` makes for device-level status. The cost is one redundant
    # `services` republish per device after a restart.
    previous_services: dict[str, tuple] = field(default_factory=dict)
    # 2026-09-25 (quick 260925-b81): device ids that had any non-empty
    # retained per-device topic at startup. This can include ghosts that are
    # NOT in the retained topology, which `previous_nodes` alone can never
    # tombstone -- that is why rebuilding a Checkmk site used to need the
    # mosquitto volume wiped too (docs section 8.5, commit 96e7182).
    # `run_cycle` sweeps it once, behind `allow_stale_sweep`, then empties it.
    retained_ids: set[str] = field(default_factory=set)
    # 2026-10-02 (Phase 16 D-10 fallback seed): faked hosts restored from the retained
    # `admin/faked` topic; only used when the site lacks `active_checks_enabled`.
    admin_faked: dict[str, str] = field(default_factory=dict)
    # 2026-10-04 (quick 261004-kbt): full topic strings of this site's retained
    # non-empty per-device history/service_history topics, cleared once by
    # `run_cycle` behind `allow_stale_sweep`. The pre-14.3 un-namespaced sweep
    # that shared this set was removed 2026-10-04 (quick 261004-lyz) after it
    # ran on the only deployment.
    retired_history_topics: set[str] = field(default_factory=set)
    # Phase 14 (PLR-14): incident id -> last-published `incident_signature()`
    # (or `None` for an id seeded by `reconcile_state` from a retained topic
    # whose payload was never parsed -- a seeded `None` always differs from
    # a freshly computed signature, forcing exactly one republish). In-memory
    # only, per PLR-14's "no incident state of its own" -- a restart
    # tombstones anything closed while it was down and republishes anything
    # still open, using the retained `lan/incidents/+/status` topics
    # themselves as the durable store, never a poller-owned file.
    previous_incidents: dict[str, tuple | None] = field(default_factory=dict)


def parse_topology_payload(payload: bytes) -> dict[str, dict]:
    """Parse a retained `lan/devices/topology` payload into `{id: node}`.

    An empty payload (the tombstone case, or "never published before") and
    malformed JSON both degrade to the empty dict rather than raising: a
    corrupt retained message must fall back to a cold start, not
    crash-loop a `restart: unless-stopped` container (T-09-05).
    """
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        _logger.warning("Malformed topology payload during reconciliation: %s", exc)
        return {}
    devices = data.get("devices", []) if isinstance(data, dict) else []
    return {
        node["id"]: _normalise_restored_node(node)
        for node in devices
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"]
    }


# Bug fixed 2026-09-11 (found at Phase 10's live checkpoint, not by the test
# suite): a retained topology message written by an EARLIER poller version
# carries an earlier node shape. Phase 10 added the `alias` key to
# `topology_nodes()` and to `topology_signature()`, so the first cycle after
# an upgrade read a retained node with no `alias` and died with
# `KeyError: 'alias'` inside `topology_signature`. Under
# `restart: unless-stopped` that is a crash-loop, because every restart
# re-reads the same retained message.
#
# The old payload is not *corrupt*, so it sailed straight past
# `parse_topology_payload`'s malformed-JSON guard — which means guarding
# harder against corruption would not have caught this. The real defect was
# treating a cross-version payload as if it had the current schema.
#
# Normalising here (rather than making `topology_signature` tolerant with
# `.get()` calls) keeps the tolerance at the single deserialisation boundary
# where the version skew actually enters, honours the cold-start-not-
# crash-loop contract this function's docstring already promises (T-09-05),
# and means the next field Phase 11 adds needs one default here instead of a
# new `.get()` at every read site.
# Bug fixed 2026-09-11 (Phase 10 code review, CR-06): the first version of this
# normalisation handled MISSING keys but not WRONG TYPES, which left the very
# contract it cited still broken. A retained payload is untrusted input, and two
# malformed-but-valid-JSON shapes were reproduced against it:
#   {"id": ["x"]}                  -> TypeError: unhashable type: 'list', raised
#                                     inside parse_topology_payload itself, so a
#                                     `restart: unless-stopped` container
#                                     crash-loops -- exactly the T-09-05 failure
#                                     this code exists to prevent.
#   {"id": "a", "parents": "r1"}   -> survives, but topology_signature computes
#                                     sorted("r1") and produces a character-
#                                     exploded tuple, a silently wrong signature
#                                     that republishes topology every cycle.
# Types are checked with `isinstance` to match how `query_devices` already
# validates these same fields, rather than introducing a second style.
#
# 2026-09 (plan 13-04): this is exactly the "next field needs one default
# here" case the comment above already predicted -- Phase 13 adds
# `map_position`/`unmanaged` to `topology_nodes()`/`topology_signature()`,
# so a retained payload written by a pre-13-04 poller has neither key.
# Backfilled the same way as every prior field: missing or wrong-type both
# fall back to the same default `topology_nodes()` itself uses for a host
# with no `host_config` entry (`None`/`False`), never a crash.
def host_config_from_topology(nodes: dict[str, dict]) -> dict[str, HostConfigInfo]:
    """Rebuild the REST host-config map from reconciled retained topology nodes.

    Seeds `last_host_config` at startup, so a REST failure on the very first cycle reuses
    the operator's labels as last published instead of defaulting every one of them. Bug
    fixed 2026-09-28 (14-REVIEW WR-06): the map used to start empty, so a transient REST
    error right after a restart republished the topology with every criticality at `low`,
    every `depends_on`/`map_position` blanked and every `unmanaged` false. That downgraded
    incidents and dissolved inferred roots until REST recovered. `nodes` must already be
    normalised by `_normalise_restored_node()`, as `reconcile_state()` guarantees.
    """
    return {
        node_id: HostConfigInfo(
            folder=node["folder"],
            map_position=node["map_position"],
            unmanaged=node["unmanaged"],
            criticality=node["criticality"],
            service_criticality=dict(node["service_criticality"]),
            depends_on=list(node["depends_on"]),
        )
        for node_id, node in nodes.items()
    }


def _normalise_restored_node(node: dict) -> dict:
    """Backfill AND type-check a node restored from a retained payload.

    Defaults match `topology_nodes()`'s own defaults, so a node that predates
    a field compares equal to a fresh node that genuinely has no value for it
    — and differs from one that does, which correctly triggers exactly one
    republish on the first cycle after an upgrade.

    A value of the wrong type is treated the same as a missing one: it falls
    back to the default rather than propagating into `topology_signature`.
    Callers must still reject a node whose `id` is not a `str` — that one
    cannot be defaulted, since it is the dict key.

    Phase 14 (D-07/D-08/D-09, plan 14-07): `criticality`/`service_criticality`/
    `depends_on` are exactly the next-field case this comment predicts --
    backfilled and type-checked the same way, so a pre-14-07 retained node
    (missing these keys) and a wrong-typed one (e.g. a hand-edited retained
    payload with `criticality: 3`) both degrade to the same safe defaults
    `topology_nodes()` produces, republish exactly once on the first cycle
    after upgrade, and never crash the poller (T-14-21).
    """
    parents = node.get("parents")
    if not isinstance(parents, list) or not all(isinstance(p, str) for p in parents):
        parents = []
    device_type = node.get("device_type")
    if not isinstance(device_type, str) or not device_type:
        device_type = UNKNOWN_DEVICE_TYPE
    folder = node.get("folder")
    if not isinstance(folder, str):
        folder = ""
    alias = node.get("alias")
    if not isinstance(alias, str):
        alias = ""
    map_position = node.get("map_position")
    if not isinstance(map_position, str):
        map_position = None
    unmanaged = node.get("unmanaged")
    if not isinstance(unmanaged, bool):
        unmanaged = False
    criticality = node.get("criticality")
    if not isinstance(criticality, str) or criticality not in CRITICALITY_TIERS:
        criticality = DEFAULT_CRITICALITY
    service_criticality = node.get("service_criticality")
    if not isinstance(service_criticality, dict):
        service_criticality = {}
    else:
        service_criticality = {
            key: value
            for key, value in service_criticality.items()
            if isinstance(key, str) and isinstance(value, str) and value in CRITICALITY_TIERS
        }
    depends_on = node.get("depends_on")
    if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
        depends_on = []
    return {
        **node,
        "parents": parents,
        "device_type": device_type,
        "folder": folder,
        "alias": alias,
        "map_position": map_position,
        "unmanaged": unmanaged,
        "criticality": criticality,
        "service_criticality": service_criticality,
        "depends_on": depends_on,
    }


def parse_events_payload(payload: bytes) -> list[dict]:
    """Parse the retained `lan/events/recent` bounded-array payload.

    Same empty/malformed-degrades-to-empty contract as
    `parse_topology_payload`.
    """
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        _logger.warning("Malformed events payload during reconciliation: %s", exc)
        return []
    return data if isinstance(data, list) else []


def reconcile_state(config: PollerConfig) -> PollerState:
    """Rebuild `PollerState` from the broker's own retained topics -- never a local file.

    Only `previous_nodes` drives tombstone and topology-change decisions,
    and it comes from exactly one retained topic (`lan/devices/topology`),
    so Mosquitto delivers exactly one message (or none, on cold start)
    right after SUBACK. There is no ambiguous "have all retained messages
    arrived yet" wait, unlike a wildcard subscription across N per-device
    topics would have (RESEARCH.md's resolved reconciliation strategy).

    The ids of every device with a retained `status`/`services` topic are
    also collected into `retained_ids`, so `run_cycle` can clear topics of
    hosts the site no longer has. Retained non-empty `history`/
    `service_history` topics (no longer published) are collected by full
    topic into `retired_history_topics` and cleared once by the same sweep.

    Per-device status is deliberately NOT reconciled at all: it is
    republished fresh from live Livestatus every cycle (`run_cycle`), so
    it has no "previous" value worth recovering.

    Phase 12 (D-13): `previous_services` is likewise deliberately NOT
    reconciled here -- see the dated comment on `PollerState` above.

    This is what satisfies "self-heals across restarts with no persisted
    state of its own" (PLR-02): the durable store is Mosquitto's
    `persistence true` from Phase 8, not a poller-owned file.

    Phase 14 (PLR-14): the ids of every host with a retained, non-empty
    `lan/incidents/{id}/status` topic are likewise collected, into
    `retained_incident_ids`, and seeded into the returned state's
    `previous_incidents` with a `None` signature -- a `None` always differs
    from a freshly computed signature, so the first cycle after a restart
    either republishes a still-open incident (no visible change to a
    viewer, since the payload is the same) or tombstones one that closed
    while the poller was down. Only the topic *name* is read here, never
    the retained payload body, per the malformed-payload posture already
    applied to the per-device topics above.

    This function's client deliberately has no will configured -- its own
    (normal) disconnect at the end of this function must never publish a
    false offline poller status for the actual running poller (T-09-06).
    """
    topology_result: list[bytes] = []
    events_result: list[bytes] = []
    retained_ids: set[str] = set()
    retained_incident_ids: set[str] = set()
    admin_faked_result: list[bytes] = []
    retired_history_topics: set[str] = set()
    topology_received = threading.Event()

    def on_message(client, userdata, msg):
        rel = relative_topic(msg.topic)
        if rel is None:
            # Not under this site's prefix: ignored.
            return
        parts = rel.split("/")
        if rel == TOPIC_ADMIN_FAKED:
            admin_faked_result.append(msg.payload)
            return
        # A zero-length payload is an already-cleared topic, not a ghost.
        # Only exact 4-segment per-device topics count (the 3-segment
        # `lan/devices/topology` never matches), and only ids that
        # `is_publishable_device_id` accepts (T-q260925-02).
        if (
            len(parts) == 4
            and parts[0] == "lan"
            and parts[1] == "devices"
            and parts[3] in ("status", "services")
            and msg.payload
            and is_publishable_device_id(parts[2])
        ):
            retained_ids.add(parts[2])
        # 2026-10-04 (quick 261004-kbt): the poller no longer publishes per-device
        # history/service_history (ClickHouse holds transition history); already-
        # retained ones are cleared once via retired_history_topics. Remove this and
        # the two subscriptions together after one release.
        if (
            len(parts) == 4
            and parts[0] == "lan"
            and parts[1] == "devices"
            and parts[3] in ("history", "service_history")
            and getattr(msg, "retain", False)
            and msg.payload
        ):
            retired_history_topics.add(msg.topic)
        if (
            len(parts) == 4
            and parts[0] == "lan"
            and parts[1] == "incidents"
            and parts[3] == "status"
            and msg.payload
            and parts[2].startswith(INCIDENT_ID_PREFIX)
            and is_publishable_device_id(parts[2])
        ):
            retained_incident_ids.add(parts[2])
        if rel == TOPIC_TOPOLOGY:
            topology_result.append(msg.payload)
            topology_received.set()
        elif rel == TOPIC_EVENTS:
            events_result.append(msg.payload)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
    client.on_message = on_message
    try:
        client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
        # The topology subscription is sent LAST on purpose. Mosquitto queues
        # a subscription's retained messages when it handles that SUBSCRIBE,
        # and packets on one connection are handled and delivered in order,
        # so once the topology message arrives the earlier wildcards'
        # retained messages have already been delivered and the
        # `topology_received.wait` below doubles as a barrier for them.
        # This is an assumption about broker ordering that has not been
        # verified live. If it is wrong the failure is safe: a missed id is
        # simply not swept, and a live host is never tombstoned.
        # The first post-upgrade start waits the full reconcile timeout once,
        # because the new-namespace topology does not exist yet.
        client.subscribe(site_topic(TOPIC_EVENTS), qos=1)
        client.subscribe(site_topic("lan/devices/+/status"), qos=1)
        client.subscribe(site_topic("lan/devices/+/history"), qos=1)
        client.subscribe(site_topic("lan/devices/+/services"), qos=1)
        client.subscribe(site_topic("lan/devices/+/service_history"), qos=1)
        client.subscribe(site_topic("lan/incidents/+/status"), qos=1)
        client.subscribe(site_topic(TOPIC_ADMIN_FAKED), qos=1)
        client.subscribe(site_topic(TOPIC_TOPOLOGY), qos=1)
        client.loop_start()
        topology_received.wait(timeout=config.reconcile_timeout_seconds)
    finally:
        client.loop_stop()
        client.disconnect()

    previous_nodes = parse_topology_payload(topology_result[0] if topology_result else b"")
    events = parse_events_payload(events_result[0] if events_result else b"")

    admin_faked_payload = admin_faked_result[0] if admin_faked_result else b""

    return PollerState(
        previous_nodes=previous_nodes,
        last_status={},
        events=events,
        since=utc_now_iso(),
        retained_ids=retained_ids,
        previous_incidents={incident_id: None for incident_id in retained_incident_ids},
        admin_faked=parse_admin_faked_payload(admin_faked_payload),
        retired_history_topics=retired_history_topics,
    )


def run_cycle(
    client: mqtt.Client,
    config: PollerConfig,
    state: PollerState,
    snapshots: list[DeviceSnapshot],
    services: list[ServiceSnapshot] | None = None,
    allow_stale_sweep: bool = False,
) -> None:
    """Run one poll cycle: publish status, detect changes, tombstone removals.

    Status publishes first for every snapshot -- it's correct regardless
    of anything else this cycle discovers. Topology/tombstone/
    events are then computed from the diff between this cycle's live
    Livestatus snapshot and `state.previous_nodes`/`state.last_status`.

    No "first cycle" suppression flag is needed: `state.last_status`
    starts empty on both a cold start and a warm restart (`reconcile_state`
    deliberately never reconciles per-device status), so a restarted
    poller mathematically cannot compute a false transition on its first
    cycle -- the suppression falls out of the data structure rather than
    needing a flag.

    Phase 12 (D-12/D-13): `services` is `None` on a cycle whose
    services query failed (or hasn't run yet) -- the status topic then
    keeps publishing every snapshot's core fields with no gauge keys at
    all, rather than publishing wrong `null`s over a good retained value,
    and `services` is not touched. When `services` is a list (including an
    empty one), each snapshot's rows are diffed via `services_signature()`
    against `state.previous_services` -- the row list republishes only on a
    real change (D-13). Transition history lives in ClickHouse, not MQTT.

    `allow_stale_sweep` (2026-09-25, quick 260925-b81): when true, retained
    per-device topics collected at startup (`state.retained_ids`) whose id is
    in neither this cycle's snapshots nor `state.previous_nodes` are
    tombstoned once, and `retained_ids` is then emptied. The caller sets it
    only when the host list is confirmed (see the gate in `run_forever`);
    when false, `retained_ids` is left intact for a later cycle. The same
    gate clears `state.retired_history_topics` (this site's retired
    history/service_history retained topics) once, with no live-id subtraction.

    Phase 14 (PLR-14/PLR-16): `compute_incidents(snapshots)` is re-derived
    from scratch every cycle -- no incident state persists between cycles
    except `state.previous_incidents`' signatures, kept only to decide
    whether to republish. An incident absent this cycle but present in
    `state.previous_incidents` is tombstoned (it closed, or `reconcile_state`
    seeded it as a startup guess that turned out stale); every incident
    still open publishes only when `incident_signature()` differs from what
    was last published, so an operator's criticality/dependency edit (which
    changes `worst_criticality`/`dependents` without changing the DOWN/
    UNREACH set) still triggers exactly one republish.
    """
    now = utc_now_iso()

    if services is not None:
        apply_visible_service_state(snapshots, services)

    services_by_host: dict[str, list[ServiceSnapshot]] = {}
    if services is not None:
        for service in services:
            services_by_host.setdefault(service.host_name, []).append(service)

    for snapshot in snapshots:
        if services is None:
            publish_device_status(client, snapshot, now)
            continue

        gauge_fields, rows = classify_host_services(services_by_host.get(snapshot.id, []))
        publish_device_status(client, snapshot, now, gauge_fields=gauge_fields)

        signature = services_signature(rows)
        if signature != state.previous_services.get(snapshot.id):
            publish_services(client, snapshot.id, rows)
            state.previous_services[snapshot.id] = signature

    nodes = topology_nodes(snapshots)
    snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    current_ids = set(snapshots_by_id)
    previous_ids = set(state.previous_nodes)
    removed_ids = previous_ids - current_ids
    added_ids = current_ids - previous_ids

    events_this_cycle: list[dict] = []

    for device_id in removed_ids:
        publish_tombstone(client, device_id)
        last_state = state.last_status.pop(device_id, None)
        # The tombstone published above already clears the broker side of
        # the per-device topics; this pop clears the in-process side so a
        # re-added host with the same id starts clean.
        state.previous_services.pop(device_id, None)
        events_this_cycle.append(
            {
                "timestamp": now,
                "device_id": device_id,
                "event": "removed",
                "from": last_state,
                "to": None,
            }
        )

    if allow_stale_sweep:
        # Ids subtracted: current (live, must never be cleared) and previous
        # (already handled by the removed loop above, avoids a double
        # tombstone). No "removed" event is emitted: these are leftovers from
        # an earlier site or poller run, not a host leaving this site, and
        # dozens of events after a rebuild would flood the bounded feed.
        stale_ids = state.retained_ids - current_ids - previous_ids
        for device_id in sorted(stale_ids):
            publish_tombstone(client, device_id)
            state.last_status.pop(device_id, None)
            state.previous_services.pop(device_id, None)
            _logger.info("Cleared stale retained topics for absent host %s", device_id)
        # The sweep runs once per process; `previous_nodes` tracks from here.
        state.retained_ids = set()
        # 2026-10-04 (quick 261004-kbt): clear this site's retired
        # history/service_history retained topics once, emitting no events.
        if state.retired_history_topics:
            for retired_topic in sorted(state.retired_history_topics):
                publish_raw_tombstone(client, retired_topic)
            _logger.info(
                "Cleared %d retired history/service_history retained topics",
                len(state.retired_history_topics),
            )
        state.retired_history_topics = set()

    for device_id in added_ids:
        events_this_cycle.append(
            {
                "timestamp": now,
                "device_id": device_id,
                "event": "added",
                "from": None,
                "to": snapshots_by_id[device_id].state,
            }
        )

    for snapshot in snapshots:
        previous_state = state.last_status.get(snapshot.id)
        if previous_state is not None and previous_state != snapshot.state:
            events_this_cycle.append(
                {
                    "timestamp": now,
                    "device_id": snapshot.id,
                    "event": "state_change",
                    "from": previous_state,
                    "to": snapshot.state,
                }
            )

    if topology_signature(nodes) != topology_signature(list(state.previous_nodes.values())):
        publish_topology(client, nodes, now)

    if events_this_cycle:
        state.events = (state.events + events_this_cycle)[-config.events_max_entries :]
        publish_events(client, state.events)

    incidents = compute_incidents(snapshots)
    current_incidents = {incident["id"]: incident for incident in incidents}
    for incident_id in sorted(set(state.previous_incidents) - set(current_incidents)):
        publish_incident_tombstone(client, incident_id)
    for incident_id, incident in current_incidents.items():
        signature = incident_signature(incident)
        if signature != state.previous_incidents.get(incident_id):
            publish_incident(client, incident, now)
    state.previous_incidents = {
        incident_id: incident_signature(incident) for incident_id, incident in current_incidents.items()
    }

    publish_poller_status(client, since=state.since, last_poll=now, device_count=len(snapshots))

    state.previous_nodes = {node["id"]: node for node in nodes}
    state.last_status = {snapshot.id: snapshot.state for snapshot in snapshots}


def run_forever(config: PollerConfig) -> int:
    """Run the poller until interrupted: reconcile, connect, then poll forever.

    Column probing happens once at startup (not per cycle) via
    `available_host_columns`/`select_host_columns`, retried on a bounded
    schedule (`_STARTUP_RETRY_DELAYS_SECONDS`) before being treated as
    fatal: a Checkmk container restart racing the poller's own start is a
    known-transient condition, observed live during Phase 10's
    verification run (10-06-SUMMARY.md finding 4), where only
    `restart: unless-stopped` recovered the poller. Only once every retry
    is exhausted does a `LivestatusError` here become fatal (the site
    still cannot answer the poller's most basic query) and return
    non-zero with a clear message naming the missing columns. Every
    subsequent per-cycle `LivestatusError` is caught and logged instead --
    the poll interval itself is the retry backoff (RESEARCH.md's "Don't
    Hand-Roll"), so no separate retry state machine is added there.
    """
    configure_logging(config.log_level)
    state = reconcile_state(config)
    admin_context = AdminContext()
    admin_context.seed_ledger(state.admin_faked)
    admin_worker = AdminCommandWorker(config, admin_context)
    client = build_mqtt_client(config, admin_worker=admin_worker)
    admin_worker.start()
    rest_base_url = cmk_rest_base_url(config)
    # Reused (never cleared) on a RestError below rather than falling back
    # to an empty dict: `folder` participates in `topology_signature`, so
    # blanking every folder on a transient REST failure would publish a
    # full spurious topology change and then publish another one when
    # REST recovered -- violating PLR-04's "republish only when topology
    # actually changes". Reusing the last known good map keeps the
    # signature stable across a REST blip (T-10-12). Phase 13 (plan
    # 13-04): `last_host_config` carries `map_position`/`unmanaged` too,
    # same reuse-on-failure reasoning -- both now participate in
    # `topology_signature`. Seeded from the retained topology so the reuse
    # also covers a REST failure on the very first cycle (14-REVIEW WR-06).
    last_host_config: dict[str, HostConfigInfo] = host_config_from_topology(state.previous_nodes)

    # OPS-03 posture decision, dated 2026-09-12: the requirement asks for
    # "one consistent failure posture" across the startup Livestatus probe
    # and the REST credential. Literal symmetry -- making this probe
    # non-fatal like the REST folder lookup below -- was considered and
    # REJECTED: Livestatus is the poller's sole mandatory data source (no
    # Livestatus means no snapshots at all, so nothing to publish), while
    # REST only enriches the `folder` field, which is why Phase 10
    # decision D-03 and the `fetch_host_folders` comment further down made
    # REST non-fatal on purpose. Making Livestatus non-fatal too would let
    # a permanently-unreachable site hang silently with no operator
    # signal. The real defect finding 4 described was the ABSENCE of any
    # retry tolerance for a known-transient race, not the fatal-on-failure
    # posture itself -- this loop fixes that absence, and exhaustion still
    # logs at error level and returns 1 below.
    columns: list[str] | None = None
    last_exc: LivestatusError | None = None
    max_attempts = len(_STARTUP_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            available = available_host_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
            columns = select_host_columns(available)
            break
        except LivestatusError as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = _STARTUP_RETRY_DELAYS_SECONDS[attempt - 1]
                _logger.warning(
                    "Startup Livestatus probe failed (attempt %d/%d): %s -- retrying in %ds",
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

    if columns is None:
        _logger.error(
            "Cannot start: Livestatus probe failed after %d attempts: %s", max_attempts, last_exc
        )
        shutdown_mqtt_client(client)
        return 1

    # Phase 12 (D-12/D-13/D-14) services column probe, deliberately
    # asymmetric with the hosts probe above: Livestatus hosts is the
    # poller's sole mandatory data source (no hosts means nothing to
    # publish at all), whereas services only adds gauges/SMART/the
    # service list -- the same enrichment-degrades posture Phase 10 D-03
    # already established for the REST folder lookup below. On retry
    # exhaustion this logs a warning and disables gauges/services for the
    # process's lifetime (until a restart re-probes) rather than treating
    # the whole poller as unable to start.
    service_columns: list[str] | None
    service_columns = None
    available_services: set[str] = set()
    last_service_exc: LivestatusError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            available_services = available_service_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
            service_columns = select_service_columns(available_services)
            break
        except LivestatusError as exc:
            last_service_exc = exc
            if attempt < max_attempts:
                delay = _STARTUP_RETRY_DELAYS_SECONDS[attempt - 1]
                _logger.warning(
                    "Startup services column probe failed (attempt %d/%d): %s -- retrying in %ds",
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

    if service_columns is None:
        _logger.warning(
            "Services probe failed after %d attempts: %s -- gauges and the per-service list "
            "are disabled until the poller restarts",
            max_attempts,
            last_service_exc,
        )

    # Phase 16 D-10: derive the faked set from Livestatus when both tables expose
    # `active_checks_enabled`; otherwise fall back to the poller-owned ledger.
    admin_context.use_ledger = (
        ADMIN_FAKED_COLUMN not in available or ADMIN_FAKED_COLUMN not in available_services
    )
    if admin_context.use_ledger:
        _logger.warning(
            "Livestatus lacks %s on hosts or services; admin faked set uses the poller ledger",
            ADMIN_FAKED_COLUMN,
        )

    # OPS-04: a greppable line in `podman logs` distinguishing a healthy
    # poller from a hung one on the first line after startup. Only the
    # four non-secret fields named by the requirement are logged --
    # `cmk_rest_secret`/`cmk_rest_username` and the whole `config` object
    # (PollerConfig.__repr__ already redacts the secret, Phase 10-03) are
    # deliberately excluded.
    _logger.info(
        "Poller started: site=%s poll_interval=%ss broker=%s:%s",
        config.cmk_site_id,
        config.poll_interval_seconds,
        config.mqtt_host,
        config.mqtt_port,
    )
    # Phase 14.1 (D-44): a greppable line stating whether history writes are
    # on, matching OPS-04's "healthy vs hung" reasoning above. Never logs
    # clickhouse_writer_password -- only the URL, which carries no secret.
    if config.clickhouse_url:
        _logger.info("History writes enabled: clickhouse_url=%s", config.clickhouse_url)
    else:
        _logger.info("History writes disabled: CLICKHOUSE_URL is unset")

    # Phase 14.1 (D-49/D-52): resolved once here, not per cycle -- a
    # missing tzdata package (research Pitfall 3) or a bad ROLLUP_TZ value
    # disables rollups for the process's lifetime rather than raising out
    # of every single cycle below.
    rollup_tz: zoneinfo.ZoneInfo | None
    try:
        rollup_tz = zoneinfo.ZoneInfo(_validate_tz_name(config.rollup_tz))
    except (zoneinfo.ZoneInfoNotFoundError, RollupError) as exc:
        _logger.error(
            "Availability rollups disabled: cannot resolve ROLLUP_TZ=%r (Pitfall 3: is the "
            "tzdata package installed?): %s",
            config.rollup_tz,
            exc,
        )
        rollup_tz = None

    scheduler = RollupScheduler(delay_minutes=config.rollup_delay_minutes)
    s3_holder: dict = {}
    if rollup_tz is not None:
        if config.clickhouse_url and config.s3_endpoint:
            _logger.info(
                "Availability rollups enabled: bucket=%s tz=%s",
                config.availability_bucket,
                config.rollup_tz,
            )
        else:
            _logger.info(
                "Availability rollups disabled: %s is unset",
                "CLICKHOUSE_URL" if not config.clickhouse_url else "S3_ENDPOINT",
            )

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop_event.is_set():
        # A host-config lookup is enrichment, not the poller's core duty
        # (RESEARCH.md Pitfall 3): unlike the mandatory Livestatus query
        # below, a RestError here degrades only the folder/map_position/
        # unmanaged fields for this cycle -- it never skips the cycle or
        # crashes the loop. One REST GET now covers folder, map_position,
        # and unmanaged (13-01 VERDICT V-LABELS-IN-COLLECTION), replacing
        # the old folder-only `fetch_host_folders()` call.
        rest_ok = False
        try:
            last_host_config = fetch_host_config(
                rest_base_url,
                config.cmk_rest_username,
                config.cmk_rest_secret,
                DEFAULT_REST_TIMEOUT_SECONDS,
            )
            rest_ok = True
        except RestError as exc:
            _logger.warning("Reusing last known host-config map; REST refresh failed: %s", exc)

        # Phase 12: a services-query failure degrades only this cycle's
        # gauges/services (D-12/D-13/D-14) -- it never skips the cycle or
        # affects the mandatory hosts query below.
        services: list[ServiceSnapshot] | None = None
        if service_columns is not None:
            try:
                services = query_services(
                    config.livestatus_host,
                    config.livestatus_port,
                    service_columns,
                    DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
                )
            except LivestatusError as exc:
                _logger.warning("Services query failed this cycle: %s", exc)
                services = None

        last_folders = {host_id: info.folder for host_id, info in last_host_config.items()}
        try:
            snapshots = query_devices(
                config.livestatus_host,
                config.livestatus_port,
                columns,
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
                folders=last_folders,
                host_config=last_host_config,
            )
        except LivestatusError as exc:
            _logger.warning("Skipping cycle: %s", exc)
        else:
            # Stale-topic sweep gate. A failed query never reaches here
            # (LivestatusError skips the cycle). A non-empty snapshot list
            # proves the site is up. An EMPTY successful result is ambiguous
            # (real zero-host site vs. a core that has not loaded its config),
            # so it is trusted only when this cycle's REST fetch succeeded
            # and independently returned zero hosts; the reused
            # `last_host_config` after a RestError is not confirmation. With
            # CMK_REST_SECRET unset REST always fails, so an empty site simply
            # never sweeps, which is the safe direction.
            run_cycle(
                client,
                config,
                state,
                snapshots,
                services=services,
                allow_stale_sweep=bool(snapshots) or (rest_ok and not last_host_config),
            )
            admin_context.update_snapshots(snapshots)
            refresh_admin_faked(client, admin_context, config)
            # Runs after MQTT publishing (run_cycle above) so a slow or dead
            # ClickHouse can never delay status (D-44). A skipped cycle
            # (the LivestatusError branch above) writes nothing at all,
            # which is the "no data" gap D-47 describes.
            write_history(config, build_history_rows(
                snapshots, services, datetime.datetime.now(datetime.UTC)
            ))
        # Outside the Livestatus try/else above -- the rollup backfill does
        # not depend on this cycle's Livestatus result (D-49/D-51/D-52).
        if rollup_tz is not None:
            maybe_run_rollups(
                config,
                scheduler,
                s3_holder,
                rollup_tz,
                datetime.datetime.now(rollup_tz),
                time.monotonic(),
            )
        stop_event.wait(timeout=config.poll_interval_seconds)

    # Graceful stop must leave the same retained value the LWT would have
    # left, so a `podman compose stop poller` and a `kill -9` look
    # identical to the dashboard.
    admin_worker.stop()
    shutdown_mqtt_client(client)
    return 0


def main() -> int:
    """CLI entry point. Runtime configuration is env-var-only (D-04); flags are diagnostics only."""
    parser = argparse.ArgumentParser(
        description="LAN poller: Livestatus -> retained MQTT topics. "
        "Runtime settings come entirely from environment variables (see PollerConfig.from_env)."
    )
    parser.add_argument(
        "--check-columns",
        action="store_true",
        help="Probe the live Livestatus site, print each REQUIRED_HOST_COLUMNS/"
        "OPTIONAL_HOST_COLUMNS name with present/missing, then exit "
        "(0 if all required columns are present, 1 otherwise).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one poll cycle then exit, for manual verification.",
    )
    parser.add_argument(
        "--dump-service-names",
        action="store_true",
        help="Print every distinct service description the live site reports, then exit -- "
        "used to confirm Checkmk's actual SMART service naming against a real host "
        "(see SMART_HEALTH_SERVICE_RE).",
    )
    args = parser.parse_args()
    config = PollerConfig.from_env()
    try:
        set_site_id(config.cmk_site_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if "CMK_SITE_ID" not in os.environ:
        _logger.warning(
            "CMK_SITE_ID is not set; using the default site id 'dmc', so the MQTT "
            "namespace is sites/dmc/. This collides with any other unconfigured "
            "site sharing the broker."
        )

    if args.check_columns:
        configure_logging(config.log_level)
        try:
            available = available_host_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
        except LivestatusError as exc:
            _logger.error("Column check failed: %s", exc)
            return 1
        ok = True
        for name in REQUIRED_HOST_COLUMNS:
            present = name in available
            ok = ok and present
            print(f"{'present' if present else 'MISSING'}: {name} (required)")
        for name in OPTIONAL_HOST_COLUMNS:
            print(f"{'present' if name in available else 'missing'}: {name} (optional)")
        print(
            f"{'present' if ADMIN_FAKED_COLUMN in available else 'missing'}: "
            f"{ADMIN_FAKED_COLUMN} (admin, optional)"
        )

        try:
            available_services = available_service_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
        except LivestatusError as exc:
            _logger.error("Services column check failed: %s", exc)
            return 1
        for name in REQUIRED_SERVICE_COLUMNS:
            present = name in available_services
            ok = ok and present
            print(f"{'present' if present else 'MISSING'}: {name} (required, services)")
        for name in OPTIONAL_SERVICE_COLUMNS:
            print(f"{'present' if name in available_services else 'missing'}: {name} (optional, services)")
        print(
            f"{'present' if ADMIN_FAKED_COLUMN in available_services else 'missing'}: "
            f"{ADMIN_FAKED_COLUMN} (admin, optional, services)"
        )
        return 0 if ok else 1

    if args.dump_service_names:
        configure_logging(config.log_level)
        try:
            body = _livestatus_request(
                config.livestatus_host,
                config.livestatus_port,
                "GET services\nColumns: description\nOutputFormat: json\n\n",
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
            )
        except LivestatusError as exc:
            _logger.error("Service name dump failed: %s", exc)
            return 1
        if not body.strip():
            descriptions: set[str] = set()
        else:
            try:
                descriptions = {row[0] for row in json.loads(body)}
            except (json.JSONDecodeError, ValueError) as exc:
                _logger.error("Service name dump failed: malformed services response: %s", exc)
                return 1
        for description in sorted(descriptions):
            print(description)
        return 0

    if args.once:
        configure_logging(config.log_level)
        state = reconcile_state(config)
        client = build_mqtt_client(config)
        try:
            available = available_host_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
            columns = select_host_columns(available)
            # Bug fixed 2026-09-11 (Phase 10 code review, CR-04): this branch
            # used to omit `folders=`, so the documented one-shot verification
            # path published retained `status` AND `topology` with every folder
            # blank -- overwriting correct retained values on the broker with
            # empty ones. Mirrors run_forever's own degrade-on-RestError
            # posture rather than inventing a new one. Phase 13 (plan 13-04):
            # `fetch_host_config()` replaces `fetch_host_folders()` here too,
            # so this one-shot path also carries map_position/unmanaged.
            once_host_config: dict[str, HostConfigInfo] = {}
            once_rest_ok = False
            try:
                once_host_config = fetch_host_config(
                    cmk_rest_base_url(config),
                    config.cmk_rest_username,
                    config.cmk_rest_secret,
                    DEFAULT_REST_TIMEOUT_SECONDS,
                )
                once_rest_ok = True
            except RestError as exc:
                _logger.warning("Host-config enrichment unavailable for this one-shot cycle: %s", exc)
            once_folders = {host_id: info.folder for host_id, info in once_host_config.items()}
            snapshots = query_devices(
                config.livestatus_host,
                config.livestatus_port,
                columns,
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
                folders=once_folders,
                host_config=once_host_config,
            )
        except LivestatusError as exc:
            _logger.error("One-shot cycle failed: %s", exc)
            shutdown_mqtt_client(client)
            return 1
        # Phase 12: same optional-services treatment as run_forever's poll
        # loop, so this documented one-shot verification path publishes the
        # same payload shape as the long-running loop -- a services failure
        # degrades only gauges/services for this one cycle, never the
        # one-shot run itself.
        once_services: list[ServiceSnapshot] | None = None
        try:
            available_services = available_service_columns(
                config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
            )
            once_service_columns = select_service_columns(available_services)
            once_services = query_services(
                config.livestatus_host,
                config.livestatus_port,
                once_service_columns,
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
            )
        except LivestatusError as exc:
            _logger.warning("Services query unavailable for this one-shot cycle: %s", exc)
        # Same sweep gate as run_forever (see the comment there).
        run_cycle(
            client,
            config,
            state,
            snapshots,
            services=once_services,
            allow_stale_sweep=bool(snapshots) or (once_rest_ok and not once_host_config),
        )
        # Same D-44 placement as run_forever's loop: after MQTT publishing,
        # so this one-shot verification path writes the same history a
        # long-running cycle would.
        write_history(config, build_history_rows(
            snapshots, once_services, datetime.datetime.now(datetime.UTC)
        ))
        shutdown_mqtt_client(client)
        return 0

    return run_forever(config)


if __name__ == "__main__":
    sys.exit(main())
