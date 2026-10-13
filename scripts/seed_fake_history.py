"""Seed (or remove) a synthetic metric history in ClickHouse for demos.

Purpose
-------
A forecast chart and a "trend" need only appear once a series has weeks of
history rising towards its critical level. This script backfills such a series
for ONE host / service / metric into `history.metrics`, ending at "now", so the
dashboard's forecast chart and analytics' trend need fire on demand instead of
after weeks of waiting.

It also sets the CURRENT state and value of that service, so the host shows
WARN/CRIT in the tree and map and the disk gauge shows the value. Run
`checkmk-wizard --demo` first: it creates a passive `Filesystem /` service on
the demo Linux host (an "Integrate Nagios plugins" rule, not live-verified).
After the history insert this script sends one Livestatus external command,

    PROCESS_SERVICE_CHECK_RESULT;<host>;<service>;<state>;<text>|<perfdata>

with state 2 if --end >= --crit, 1 if --end >= --warn, else 0 and perf data
`<metric>=<end>;<warn>;<crit>;0;100`. The state comes from --end (the requested
current value), not from the noisy last point. Channel: Livestatus TCP from the
worker container (--livestatus-host/--livestatus-port, else LIVESTATUS_HOST /
LIVESTATUS_PORT, else checkmk:6557; plain-text Livestatus, as the wizard needs).
Limits: Checkmk silently ignores a result for a service that does not exist;
the result is passive and stays until replaced; the poller then writes one
history row per cycle at that value (a flat tail). `--delete` first resets the
service to OK WITHOUT perf data, then deletes the history rows.
`--no-check-result` skips all Livestatus traffic. Use it on a `--demo` host.

Identifying and removing fake rows
----------------------------------
The schema has no marker column, so fake rows are identifiable only by their
host. Use this on a `checkmk-wizard --demo` host: it has no agent, therefore no
real metric rows. On a real host `--delete` would also remove that host's real
rows of the same service/metric. `--delete` runs

    ALTER TABLE history.metrics DELETE WHERE host = '<h>' AND service = '<s>'
        AND metric = '<m>'

as the ClickHouse admin user (poller_writer and analytics_writer only have
SELECT/INSERT, so they cannot delete). The equivalent one-off statement:

    podman exec -i clickhouse clickhouse-client --user ch_admin \\
        --password "$CH_ADMIN_PASSWORD" \\
        --query "ALTER TABLE history.metrics DELETE WHERE host = '<host>'"

Where it runs
-------------
ClickHouse publishes no host port: its HTTP interface (8123) is reachable only
on the compose network. Run the script in the worker container, which mounts the
repo at /app/checkmk-wizard:

    podman exec -it automation-worker bash -c \\
        "cd /app/checkmk-wizard && python3 scripts/seed_fake_history.py \\
         --host demo-lnx1 --dry-run"

or pass a reachable `--url`. Standard library only; the fit and tier logic is
imported from `analytics/` (also standard library only) so `--dry-run` predicts
what analytics will do. The preview uses the code DEFAULTS: environment
overrides set on the analytics container (FIT_R2_MIN, TIER_*_DAYS, ...) are not
visible here and are not applied.

Config: `deploy/.env` is read (without overriding the real environment).
URL: `--url`, else CLICKHOUSE_URL, else http://clickhouse:8123. Insert user:
CLICKHOUSE_WRITER_USER (default poller_writer) with CLICKHOUSE_WRITER_PASSWORD
or CH_WRITER_PASSWORD. Delete user: CLICKHOUSE_ADMIN_USER (default ch_admin)
with CH_ADMIN_PASSWORD. Passwords travel only in the X-ClickHouse-Key header.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# The wizard's stdlib-only Livestatus helper (works from a plain checkout, no install).
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from analytics.config import (
    CONFIDENCE_HIGH_DAYS,
    CONFIDENCE_MEDIUM_DAYS,
    DEFAULT_FIT_MIN_RISE_30D,
    DEFAULT_FIT_R2_HIGH,
    DEFAULT_FIT_R2_MIN,
    DEFAULT_NEED_HORIZON_DAYS,
    DEFAULT_TIER_IMMEDIATE_DAYS,
    DEFAULT_TIER_URGENT_DAYS,
    DEFAULT_TREND_NEED_METRICS,
    DROP_MIN_ABS,
    DROP_RANGE_FRACTION,
    FIT_BUCKET_HOURS,
    FIT_LOOKBACK_DAYS,
    FIT_MIN_BUCKETS,
    FIT_MIN_SPAN_DAYS,
    METRIC_NAME_RE,
    SUSTAINED_FRACTION,
    SUSTAINED_WINDOW_HOURS,
)
from analytics.fit import FitParams, fit_series
from analytics.rules import RuleParams, tier_from_days
from checkmk_wizard import livestatus

DEFAULT_URL = "http://clickhouse:8123"
DEFAULT_WRITER_USER = "poller_writer"
DEFAULT_ADMIN_USER = "ch_admin"
INSERT_SQL = "INSERT INTO history.metrics FORMAT JSONEachRow"
BATCH_SIZE = 5000
EVAL_INTERVAL_SECONDS = 900  # analytics DEFAULT_EVAL_INTERVAL_SECONDS

DEFAULT_LIVESTATUS_HOST = "checkmk"
_STATE_NAMES = ("OK", "WARN", "CRIT")
# Kept in step with wizard._DEMO_FILESYSTEM_OUTPUT (default service only).
_RESET_TEXT = "demo filesystem, no value seeded yet (run scripts/seed_fake_history.py)"

_HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,253}$")
_DAY = 86400.0

FIT_PARAMS = FitParams(
    bucket_hours=FIT_BUCKET_HOURS,
    min_buckets=FIT_MIN_BUCKETS,
    min_span_days=FIT_MIN_SPAN_DAYS,
    r2_min=DEFAULT_FIT_R2_MIN,
    r2_high=DEFAULT_FIT_R2_HIGH,
    min_rise_30d=DEFAULT_FIT_MIN_RISE_30D,
    drop_min_abs=DROP_MIN_ABS,
    drop_range_fraction=DROP_RANGE_FRACTION,
    confidence_medium_days=CONFIDENCE_MEDIUM_DAYS,
    confidence_high_days=CONFIDENCE_HIGH_DAYS,
)
RULE_PARAMS = RuleParams(
    immediate_days=DEFAULT_TIER_IMMEDIATE_DAYS,
    urgent_days=DEFAULT_TIER_URGENT_DAYS,
    horizon_days=DEFAULT_NEED_HORIZON_DAYS,
    trend_need_metrics=frozenset(DEFAULT_TREND_NEED_METRICS),
    sustained_fraction=SUSTAINED_FRACTION,
)


# --- argument parsing ----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_fake_history.py",
        description=(
            "Backfill a synthetic metric series into ClickHouse history.metrics "
            "and set the faked service's current state/value via Livestatus "
            "(demo aid; run `checkmk-wizard --demo` first). Run it in the worker "
            "container; ClickHouse publishes no host port."
        ),
        epilog=(
            "The expected-outcome preview uses the analytics code defaults; the "
            "analytics container's environment overrides are not applied. "
            "The check result goes to Livestatus (--livestatus-host/--livestatus-port, "
            "default checkmk:6557); --no-check-result skips it. "
            "--delete needs the ch_admin password (CH_ADMIN_PASSWORD) because "
            "poller_writer/analytics_writer only have SELECT/INSERT. One-off "
            "alternative: podman exec -i clickhouse clickhouse-client --user "
            "ch_admin --password \"$CH_ADMIN_PASSWORD\" --query \"ALTER TABLE "
            "history.metrics DELETE WHERE host = '<host>'\""
        ),
    )
    parser.add_argument("--host", required=True, help="Checkmk host name (use a demo host)")
    parser.add_argument("--service", default="Filesystem /", help="service description")
    parser.add_argument("--metric", default="fs_used_percent", help="metric name")
    parser.add_argument("--days", type=float, default=60.0, help="history length in days (>= 2)")
    parser.add_argument("--start", type=float, default=60.0, help="value at the start (0..100)")
    parser.add_argument("--end", type=float, default=84.0, help="value now (0..100)")
    parser.add_argument("--noise", type=float, default=0.5, help="gaussian noise sigma")
    parser.add_argument("--step-hours", type=float, default=1.0, help="hours between rows")
    parser.add_argument("--warn", type=float, default=80.0, help="warn level stored on each row")
    parser.add_argument("--crit", type=float, default=90.0, help="crit level stored on each row")
    parser.add_argument(
        "--sawtooth",
        type=float,
        default=None,
        metavar="DAYS",
        help="period: climb start->end each period, drop back at each boundary",
    )
    parser.add_argument("--seed", type=int, default=42, help="noise seed (reproducible)")
    parser.add_argument("--dry-run", action="store_true", help="print summary and expected fit only")
    parser.add_argument("--delete", action="store_true", help="remove the seeded series (ch_admin)")
    parser.add_argument("--url", default=None, help=f"ClickHouse HTTP URL (default {DEFAULT_URL})")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--no-check-result",
        action="store_true",
        help="do not send/reset the service check result via Livestatus",
    )
    parser.add_argument(
        "--livestatus-host",
        default=None,
        help=f"Livestatus host (default env LIVESTATUS_HOST, else {DEFAULT_LIVESTATUS_HOST})",
    )
    parser.add_argument(
        "--livestatus-port",
        type=int,
        default=None,
        help=f"Livestatus TCP port (default env LIVESTATUS_PORT, else {livestatus.DEFAULT_PORT})",
    )
    parser.add_argument("--env-file", default=None, help="env file (default deploy/.env)")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not _HOST_RE.fullmatch(args.host):
        parser.error("--host must match [A-Za-z0-9_.-]{1,253}")
    if ";" in args.service or "'" in args.service or "\\" in args.service or any(
        ord(c) < 32 or ord(c) == 127 for c in args.service
    ):
        parser.error("--service must not contain ;, ', \\ or control characters")
    if not args.service:
        parser.error("--service must not be empty")
    if not METRIC_NAME_RE.fullmatch(args.metric):
        parser.error(f"--metric must match {METRIC_NAME_RE.pattern}")
    if not math.isfinite(args.days) or args.days < FIT_MIN_SPAN_DAYS:
        parser.error(f"--days must be >= {FIT_MIN_SPAN_DAYS:g} (the fit needs that span)")
    if not math.isfinite(args.step_hours) or args.step_hours <= 0 or args.step_hours > 24:
        parser.error("--step-hours must be > 0 and <= 24")
    for name in ("start", "end"):
        value = getattr(args, name)
        if not math.isfinite(value) or not 0 <= value <= 100:
            parser.error(f"--{name} must be within 0..100")
    if not math.isfinite(args.noise) or args.noise < 0:
        parser.error("--noise must be >= 0")
    if not (math.isfinite(args.warn) and math.isfinite(args.crit)) or args.warn >= args.crit:
        parser.error("--warn must be lower than --crit")
    if args.sawtooth is not None and (
        not math.isfinite(args.sawtooth) or args.sawtooth <= 0 or args.sawtooth > args.days
    ):
        parser.error("--sawtooth must be > 0 and <= --days")
    if args.delete and args.dry_run:
        parser.error("--delete cannot be combined with --dry-run")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    if args.livestatus_port is not None and not 1 <= args.livestatus_port <= 65535:
        parser.error("--livestatus-port must be within 1..65535")
    return args


# --- series generation -----------------------------------------------------------


def generate_points(
    days: float,
    start: float,
    end: float,
    step_hours: float,
    noise: float,
    sawtooth_days: float | None,
    seed: int,
    end_ts: float,
) -> list[tuple[float, float]]:
    """Ascending (unix_ts, value) points; the last point is exactly `end_ts`.

    With noise 0 values go linearly from `start` to `end` (or, with
    `sawtooth_days`, climb start->end per period and drop back at each period
    boundary, the last tooth ending at `end`). Reproducible via `seed`.
    """
    count = math.floor(days * 24 / step_hours) + 1
    rng = random.Random(seed)
    step = step_hours * 3600
    end_ts = int(end_ts)
    points: list[tuple[float, float]] = []
    for i in range(count):
        age = (count - 1 - i) * step  # seconds before the last point
        ts = end_ts - age
        if sawtooth_days is None:
            frac = i / (count - 1)
        else:
            period = sawtooth_days * _DAY
            frac = 1 - (age % period) / period
        value = start + (end - start) * frac
        if noise > 0:
            value += rng.gauss(0, noise)
        points.append((float(int(ts)), min(100.0, max(0.0, value))))
    return points


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S")


def build_rows(
    points: list[tuple[float, float]],
    host: str,
    service: str,
    metric: str,
    warn: float,
    crit: float,
) -> list[dict]:
    """Rows shaped like scripts/mqtt_poller.py metric rows.

    value_min/max/sum/count are left out so the column DEFAULTs apply.
    """
    return [
        {
            "ts": _stamp(ts),
            "host": host,
            "service": service,
            "metric": metric,
            "value": round(value, 4),
            "warn": warn,
            "crit": crit,
        }
        for ts, value in points
    ]


def bucket_means(
    points: list[tuple[float, float]], bucket_hours: int
) -> list[tuple[float, float]]:
    """Mean per bucket of the UTC epoch, like analytics.history.fetch_fit_buckets."""
    size = bucket_hours * 3600
    sums: dict[int, list[float]] = {}
    for ts, value in points:
        sums.setdefault(int(ts // size) * size, []).append(value)
    return [(float(b), sum(v) / len(v)) for b, v in sorted(sums.items())]


def expected_outcome(
    points: list[tuple[float, float]], metric: str, warn: float, crit: float, now_ts: float
) -> dict:
    """What analytics' fit and trend-need gating will make of these points."""
    cutoff = now_ts - FIT_LOOKBACK_DAYS * _DAY
    buckets = bucket_means([p for p in points if p[0] >= cutoff], FIT_PARAMS.bucket_hours)
    fit = fit_series(buckets, warn, crit, FIT_PARAMS, now_ts)
    window = [v for t, v in points if t >= now_ts - SUSTAINED_WINDOW_HOURS * 3600]
    last = points[-1][1] if points else None
    fraction = sum(1 for v in window if v >= crit) / len(window) if window else 0.0
    sustained = fraction >= RULE_PARAMS.sustained_fraction or (
        metric in RULE_PARAMS.trend_need_metrics and last is not None and last >= crit
    )

    tier: str | None = None
    if metric not in RULE_PARAMS.trend_need_metrics:
        reason = "no trend need: metric not in TREND_NEED_METRICS"
    elif fit.status != "trending":
        reason = f"no trend need: fit status is {fit.status}"
    elif fit.days_to_crit is None or fit.crit is None:
        reason = "no trend need: no days-to-crit available"
    elif fit.last_value is not None and fit.last_value >= fit.crit:
        reason = "no trend need: already at/above crit (a sustained need may fire instead)"
    else:
        tier = tier_from_days(fit.days_to_crit, RULE_PARAMS)
        reason = (
            "" if tier is not None
            else f"no trend need: more than {RULE_PARAMS.horizon_days:g} days to crit"
        )
    return {
        "status": fit.status,
        "slope_per_day": fit.slope_per_day,
        "r2": fit.r2,
        "history_days": fit.history_days,
        "confidence": fit.confidence,
        "days_to_warn": fit.days_to_warn,
        "days_to_crit": fit.days_to_crit,
        "warn_date": fit.warn_date,
        "crit_date": fit.crit_date,
        "last_value": fit.last_value,
        "tier": tier,
        "reason": reason,
        "sustained": sustained,
    }


# --- Livestatus check result -----------------------------------------------------


def check_state(end: float, warn: float, crit: float) -> int:
    """Service state for the requested current value: 2 CRIT, 1 WARN, 0 OK."""
    if end >= crit:
        return 2
    if end >= warn:
        return 1
    return 0


def perf_data(metric: str, end: float, warn: float, crit: float) -> str:
    """Nagios perf data `label=value;warn;crit;min;max` (no UOM), 0..100 range."""
    return f"{metric}={end:.1f};{warn:g};{crit:g};0;100"


def check_output(service: str, end: float, warn: float, crit: float, state: int) -> str:
    return (
        f"{_STATE_NAMES[state]} - {service}: {end:.1f}% used "
        f"(warn/crit at {warn:g}%/{crit:g}%)"
    )


def check_result_command(
    host: str, service: str, metric: str, end: float, warn: float, crit: float
) -> str:
    """The external command that sets the service's current state and value.

    Inputs were validated by parse_args (host charset, no `;` in service); numbers
    are formatted here, so the text holds no field separator and no CR/LF.
    """
    state = check_state(end, warn, crit)
    return (
        f"PROCESS_SERVICE_CHECK_RESULT;{host};{service};{state};"
        f"{check_output(service, end, warn, crit, state)}|{perf_data(metric, end, warn, crit)}"
    )


def reset_command(host: str, service: str) -> str:
    """OK result with NO perf data: the poller writes no further rows from it."""
    return f"PROCESS_SERVICE_CHECK_RESULT;{host};{service};0;OK - {service}: {_RESET_TEXT}"


def send_check_command(host: str, port: int, command: str) -> None:
    livestatus.send_commands(host, [command], port)


def _livestatus_failure(exc: Exception, host: str, port: int, command: str, history_done: str) -> int:
    print(
        f"error: could not send the check result via Livestatus {host}:{port} ({exc}). "
        f"{history_done} Run as the site user instead (also check LIVESTATUS_TCP_TLS is off):\n"
        f'  lq "COMMAND [$(date +%s)] {command}"',
        file=sys.stderr,
    )
    return 1


# --- ClickHouse ------------------------------------------------------------------


def insert_body(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(row, allow_nan=False) for row in rows).encode("utf-8")


def delete_sql(host: str, service: str, metric: str) -> str:
    # Inputs were validated by parse_args (host charset, no quote/backslash in
    # service, metric regex), so single-quoting them is safe.
    return (
        "ALTER TABLE history.metrics DELETE WHERE "
        f"host = '{host}' AND service = '{service}' AND metric = '{metric}'"
    )


def clickhouse_post(url: str, user: str, password: str, data: bytes, timeout: float) -> bytes:
    """POST to ClickHouse. The password only goes in a header, never in the URL
    or in any raised message."""
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"X-ClickHouse-User": user, "X-ClickHouse-Key": password},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()[:300].decode(errors="replace")
        except Exception:  # noqa: BLE001 - a synthetic HTTPError may have no body
            body = ""
        raise RuntimeError(f"ClickHouse POST to {url} failed: HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise RuntimeError(f"ClickHouse POST to {url} failed: {exc}") from exc


# --- env / output ------------------------------------------------------------------


def load_env_file(path: Path) -> None:
    """Simple KEY=VALUE lines; never overrides variables already set."""
    try:
        text = path.read_text()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def print_summary(args, points, rows, outcome, now_ts) -> None:
    values = [v for _, v in points]
    print(f"Series: host={args.host} service={args.service!r} metric={args.metric}")
    print(f"Rows:   {len(rows)} (every {args.step_hours:g} h)")
    print(f"Window: {_stamp(points[0][0])} .. {_stamp(points[-1][0])} UTC")
    print(
        f"Values: first {values[0]:.2f}, last {values[-1]:.2f}, "
        f"min {min(values):.2f}, max {max(values):.2f}; warn {args.warn:g}, crit {args.crit:g}"
    )
    print("Expected analytics outcome (code defaults, no env overrides):")
    print(f"  fit status:     {outcome['status']}")
    print(f"  slope per day:  {_fmt(outcome['slope_per_day'], 3)}")
    print(f"  r2:             {_fmt(outcome['r2'], 3)}")
    print(f"  history days:   {_fmt(outcome['history_days'], 1)}")
    print(f"  confidence:     {outcome['confidence'] or 'n/a'}")
    print(
        f"  days to warn:   {_fmt(outcome['days_to_warn'], 1)} ({outcome['warn_date']})"
        if outcome["warn_date"]
        else f"  days to warn:   {_fmt(outcome['days_to_warn'], 1)}"
    )
    print(
        f"  days to crit:   {_fmt(outcome['days_to_crit'], 1)} ({outcome['crit_date']})"
        if outcome["days_to_crit"] is not None
        else "  days to crit:   n/a"
    )
    if outcome["tier"]:
        print(f"  expected trend need tier: {outcome['tier']}")
    else:
        print(f"  expected trend need: none ({outcome['reason']})")
    if outcome["sustained"]:
        print("  a sustained (immediate) need would also fire: the series sits at/above crit")
    print(
        f"Analytics evaluates every {EVAL_INTERVAL_SECONDS // 60} minutes "
        f"(EVAL_INTERVAL_SECONDS={EVAL_INTERVAL_SECONDS}); the need/forecast appears "
        "after the next slow cycle."
    )


def _require_password(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    print(f"error: set {' or '.join(names)} (e.g. via deploy/.env)", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None, now_ts: float | None = None) -> int:
    args = parse_args(argv)
    env_file = Path(args.env_file) if args.env_file else _REPO_ROOT / "deploy" / ".env"
    load_env_file(env_file)
    now = int(now_ts if now_ts is not None else time.time())

    if args.days > FIT_LOOKBACK_DAYS:
        print(
            f"warning: --days {args.days:g} > {FIT_LOOKBACK_DAYS}: rows older than "
            f"{FIT_LOOKBACK_DAYS} days are ignored by the fit",
            file=sys.stderr,
        )
    if args.sawtooth is not None and args.end - args.start <= DROP_MIN_ABS:
        print(
            f"warning: --sawtooth with end - start <= {DROP_MIN_ABS:g}: the drop is not "
            "'sharp' for analytics and will not cut the series",
            file=sys.stderr,
        )

    points = generate_points(
        args.days, args.start, args.end, args.step_hours, args.noise, args.sawtooth, args.seed, now
    )
    rows = build_rows(points, args.host, args.service, args.metric, args.warn, args.crit)
    outcome = expected_outcome(points, args.metric, args.warn, args.crit, now)
    print_summary(args, points, rows, outcome, now)
    command = check_result_command(
        args.host, args.service, args.metric, args.end, args.warn, args.crit
    )
    if args.dry_run:
        if args.no_check_result:
            print("Check result: skipped (--no-check-result)")
        else:
            print(f"Check result (not sent): {command}")
        return 0

    ls_host = (
        args.livestatus_host or os.environ.get("LIVESTATUS_HOST") or DEFAULT_LIVESTATUS_HOST
    )
    ls_port = args.livestatus_port
    if ls_port is None:
        raw_port = os.environ.get("LIVESTATUS_PORT", "")
        ls_port = int(raw_port) if raw_port.isdigit() else livestatus.DEFAULT_PORT

    base = (args.url or os.environ.get("CLICKHOUSE_URL") or DEFAULT_URL).rstrip("/")
    try:
        if args.delete:
            user = os.environ.get("CLICKHOUSE_ADMIN_USER") or DEFAULT_ADMIN_USER
            password = _require_password("CH_ADMIN_PASSWORD")
            if not args.no_check_result:
                # Reset first so the poller stops writing rows from the old perf data.
                reset = reset_command(args.host, args.service)
                try:
                    send_check_command(ls_host, ls_port, reset)
                except OSError as exc:
                    return _livestatus_failure(
                        exc, ls_host, ls_port, reset, "No history rows were deleted."
                    )
                print(f"Reset {args.service} on {args.host} to OK (no value) via Livestatus {ls_host}:{ls_port}.")
            clickhouse_post(
                f"{base}/?mutations_sync=1",
                user,
                password,
                delete_sql(args.host, args.service, args.metric).encode("utf-8"),
                args.timeout,
            )
            print(
                f"Deleted the rows of host={args.host} service={args.service!r} "
                f"metric={args.metric}. One-off equivalent: podman exec -i clickhouse "
                f'clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" '
                f"--query \"ALTER TABLE history.metrics DELETE WHERE host = '{args.host}'\""
            )
            return 0

        user = os.environ.get("CLICKHOUSE_WRITER_USER") or DEFAULT_WRITER_USER
        password = _require_password("CLICKHOUSE_WRITER_PASSWORD", "CH_WRITER_PASSWORD")
        url = f"{base}/?query={urllib.parse.quote(INSERT_SQL)}"
        for offset in range(0, len(rows), BATCH_SIZE):
            clickhouse_post(
                url, user, password, insert_body(rows[offset : offset + BATCH_SIZE]), args.timeout
            )
        print(f"Inserted {len(rows)} rows into history.metrics.")
        if not args.no_check_result:
            try:
                send_check_command(ls_host, ls_port, command)
            except OSError as exc:
                return _livestatus_failure(
                    exc, ls_host, ls_port, command, "The history rows were already inserted."
                )
            state = _STATE_NAMES[check_state(args.end, args.warn, args.crit)]
            print(
                f"Set {args.service} on {args.host} to {state} ({args.end:g}%) "
                f"via Livestatus {ls_host}:{ls_port}."
            )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
