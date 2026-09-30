"""Live smoke test proving HIST-08, HIST-09 and HIST-10 against a running dashboard.

D-54 builds a same-origin, read-only HTTP path from the dashboard's nginx to
ClickHouse's HTTP interface and to the rollup objects in MinIO; D-55 requires
Grafana to reject anonymous access. This project's `tests/` suite is 100%
mocked and never touches live infrastructure (see `tests/test_*.py`), so it
cannot prove that nginx's GET-only allowlist and ClickHouse's own readonly=1
enforcement actually hold, or that Grafana's login gate is really enabled.
This script is deliberately standalone, run via
`uv run python scripts/smoke_test_history_proxy.py --host HOST` against a
real deployment host — not collected by pytest (no `test_*` function names,
not under `tests/`).

Each check proves one property of the read path:
- `check_ch_query_via_proxy` — a plain SELECT through `/ch-api/` reaches
  ClickHouse and returns real data (the read half of D-54).
- `check_ch_post_denied` — nginx's `limit_except GET` rejects any non-GET
  method before it reaches ClickHouse.
- `check_ch_write_over_get_denied` — an INSERT attempted as a GET query
  string is refused (ClickHouse's server-side readonly=1, verified via
  context7 against ContextAccess.cpp: HTTP GET forces readonly), and the
  row is confirmed absent afterward rather than trusting the status code
  alone.
- `check_ch_ddl_denied` / `check_ch_system_tables_denied` — DDL, a client
  `SETTINGS readonly = 0` override, and `system.users` access are all
  refused by the same server-side enforcement.
- `check_ch_credential_override_denied` — nginx's `if ($arg_user)` /
  `if ($arg_password)` guards refuse a client attempt to pick another
  ClickHouse user via query string.
- `check_ch_other_paths_404` — every path under `/ch-api/` other than the
  exact endpoint (ClickHouse's own `/play`, `/ping`, `/replicas_status`,
  `/dashboard` admin/UI surface) 404s rather than reaching ClickHouse.
- `check_rollup_json_get` / `check_rollup_parquet_get` — the two rollup
  object shapes are reachable read-only through `/availability/`.
- `check_rollup_write_denied` / `check_bucket_anonymous_write_denied` —
  PUT/DELETE are refused both through the dashboard proxy and directly
  against MinIO's anonymous download-only bucket policy (D-56).
- `check_grafana_requires_login` — Grafana refuses an unauthenticated API
  request (D-55); if `--grafana-password` is given, it also confirms the
  authenticated admin session can see the three provisioned dashboards.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# D-49: rollup day boundaries are site-local time, Asia/Singapore.
_ROLLUP_TZ = ZoneInfo("Asia/Singapore")

# A host name that will never collide with a real onboarded host, used to
# probe whether a write attempted through the read-only path took effect.
_PROBE_HOST = "smoke-test-history"


def _http(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, bytes]:
    """Issue one HTTP request, normalizing every outcome to (status, body).

    An HTTPError (any non-2xx response) still carries a real status code and
    body, so it is unpacked rather than raised. A connection-level failure
    (unreachable host, refused connection, timeout) has no status code at
    all; it is reported as status 0 so every check function can compare
    against an expected integer without a try/except of its own — the same
    single-choke-point normalization this project's `fetch_host_config()`
    uses for `RestError` (`scripts/mqtt_poller.py`).
    """
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, str(exc).encode()


def check_ch_query_via_proxy(dashboard_base: str, timeout: float) -> bool:
    """GET /ch-api/?query=... reaches ClickHouse as dashboard_reader and returns data."""
    query = "SELECT count() AS n FROM history.host_state FORMAT JSONEachRow"
    url = f"{dashboard_base}/ch-api/?query={urllib.parse.quote(query)}"
    status, body = _http("GET", url, timeout=timeout)
    if status != 200:
        print(f"[FAIL] ch_query_via_proxy: expected 200, got {status}")
        return False
    try:
        row = json.loads(body.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as exc:
        print(f"[FAIL] ch_query_via_proxy: could not parse JSONEachRow response: {exc}")
        return False
    if "n" not in row:
        print(f"[FAIL] ch_query_via_proxy: response row missing key 'n': {row!r}")
        return False
    print("[PASS] ch_query_via_proxy")
    return True


def check_ch_post_denied(dashboard_base: str, timeout: float) -> bool:
    """nginx's limit_except GET refuses any non-GET method on /ch-api/."""
    status, _ = _http("POST", f"{dashboard_base}/ch-api/", data=b"SELECT 1", timeout=timeout)
    if status != 403:
        print(f"[FAIL] ch_post_denied: expected 403, got {status}")
        return False
    print("[PASS] ch_post_denied")
    return True


def check_ch_write_over_get_denied(dashboard_base: str, timeout: float) -> bool:
    """An INSERT sent as a GET query string never actually writes a row.

    Does not trust the status code alone (ClickHouse's readonly enforcement
    is verified in Pitfall/A1 to be belt-and-braces with nginx, but a status
    check alone could be fooled by a proxy quirk) — reads the table back
    afterward and asserts the probe host is still absent.
    """
    insert_query = (
        "INSERT INTO history.host_state (ts, host, folder, state, in_downtime) "
        f"VALUES (now(), '{_PROBE_HOST}', '', 0, 0)"
    )
    url = f"{dashboard_base}/ch-api/?query={urllib.parse.quote(insert_query)}"
    status, _ = _http("GET", url, timeout=timeout)
    if status == 200:
        print("[FAIL] ch_write_over_get_denied: INSERT-as-GET returned 200")
        return False
    check_query = f"SELECT count() AS n FROM history.host_state WHERE host = '{_PROBE_HOST}' FORMAT JSONEachRow"
    check_url = f"{dashboard_base}/ch-api/?query={urllib.parse.quote(check_query)}"
    check_status, check_body = _http("GET", check_url, timeout=timeout)
    if check_status != 200:
        print(f"[FAIL] ch_write_over_get_denied: could not verify row absence, GET returned {check_status}")
        return False
    try:
        row = json.loads(check_body.splitlines()[0])
        row_count = int(row["n"])
    except (json.JSONDecodeError, IndexError, KeyError, ValueError) as exc:
        print(f"[FAIL] ch_write_over_get_denied: could not parse verification response: {exc}")
        return False
    if row_count != 0:
        print(f"[FAIL] ch_write_over_get_denied: INSERT-as-GET wrote {row_count} row(s)")
        return False
    print("[PASS] ch_write_over_get_denied")
    return True


def check_ch_ddl_denied(dashboard_base: str, timeout: float) -> bool:
    """DDL and a client-supplied readonly=0 settings override are both refused."""
    ddl_status, _ = _http(
        "GET",
        f"{dashboard_base}/ch-api/?query={urllib.parse.quote('DROP TABLE history.metrics')}",
        timeout=timeout,
    )
    if ddl_status == 200:
        print("[FAIL] ch_ddl_denied: DROP TABLE returned 200")
        return False
    settings_status, _ = _http(
        "GET",
        f"{dashboard_base}/ch-api/?query={urllib.parse.quote('SELECT 1 SETTINGS readonly = 0')}",
        timeout=timeout,
    )
    if settings_status == 200:
        print("[FAIL] ch_ddl_denied: SETTINGS readonly = 0 override returned 200")
        return False
    print("[PASS] ch_ddl_denied")
    return True


def check_ch_system_tables_denied(dashboard_base: str, timeout: float) -> bool:
    """The dashboard_reader user cannot read system.users through the proxy."""
    status, _ = _http(
        "GET",
        f"{dashboard_base}/ch-api/?query={urllib.parse.quote('SELECT name FROM system.users')}",
        timeout=timeout,
    )
    if status == 200:
        print("[FAIL] ch_system_tables_denied: SELECT FROM system.users returned 200")
        return False
    print("[PASS] ch_system_tables_denied")
    return True


def check_ch_credential_override_denied(dashboard_base: str, timeout: float) -> bool:
    """nginx refuses a client-supplied user/password query arg before proxying."""
    both_status, _ = _http(
        "GET", f"{dashboard_base}/ch-api/?user=ch_admin&password=x&query=SELECT%201", timeout=timeout
    )
    if both_status != 403:
        print(f"[FAIL] ch_credential_override_denied: user+password args expected 403, got {both_status}")
        return False
    password_only_status, _ = _http(
        "GET", f"{dashboard_base}/ch-api/?password=x&query=SELECT%201", timeout=timeout
    )
    if password_only_status != 403:
        print(f"[FAIL] ch_credential_override_denied: password-only arg expected 403, got {password_only_status}")
        return False
    print("[PASS] ch_credential_override_denied")
    return True


def check_ch_other_paths_404(dashboard_base: str, timeout: float) -> bool:
    """Everything under /ch-api/ other than the exact endpoint 404s."""
    ok = True
    for suffix in ("play", "ping", "replicas_status", "dashboard", "x"):
        status, _ = _http("GET", f"{dashboard_base}/ch-api/{suffix}", timeout=timeout)
        if status != 404:
            print(f"[FAIL] ch_other_paths_404: /ch-api/{suffix} expected 404, got {status}")
            ok = False
    if ok:
        print("[PASS] ch_other_paths_404")
    return ok


def check_rollup_json_get(dashboard_base: str, date: str, timeout: float) -> bool:
    """The day's JSON rollup object is readable through /availability/."""
    year, month = date[:4], date[5:7]
    key = f"availability/{year}/{month}/{date}.json"
    status, body = _http("GET", f"{dashboard_base}/availability/{key}", timeout=timeout)
    if status != 200:
        print(f"[FAIL] rollup_json_get: expected 200, got {status}")
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] rollup_json_get: response body is not valid JSON: {exc}")
        return False
    if payload.get("schema_version") != 1:
        print(f"[FAIL] rollup_json_get: expected schema_version == 1, got {payload.get('schema_version')!r}")
        return False
    if payload.get("date") != date:
        print(f"[FAIL] rollup_json_get: expected date == {date!r}, got {payload.get('date')!r}")
        return False
    print("[PASS] rollup_json_get")
    return True


def check_rollup_parquet_get(dashboard_base: str, date: str, timeout: float) -> bool:
    """The day's Parquet rollup object is readable through /availability/."""
    key = f"availability_parquet/date={date}/availability.parquet"
    status, body = _http("GET", f"{dashboard_base}/availability/{key}", timeout=timeout)
    if status != 200:
        print(f"[FAIL] rollup_parquet_get: expected 200, got {status}")
        return False
    if not body.startswith(b"PAR1"):
        print("[FAIL] rollup_parquet_get: response body does not start with the Parquet magic bytes")
        return False
    print("[PASS] rollup_parquet_get")
    return True


def check_rollup_write_denied(dashboard_base: str, date: str, timeout: float) -> bool:
    """PUT/DELETE on a rollup object, and any bucket-listing attempt, are refused."""
    year, month = date[:4], date[5:7]
    key = f"availability/{year}/{month}/{date}.json"
    put_status, _ = _http("PUT", f"{dashboard_base}/availability/{key}", data=b"{}", timeout=timeout)
    if put_status != 403:
        print(f"[FAIL] rollup_write_denied: PUT expected 403, got {put_status}")
        return False
    delete_status, _ = _http("DELETE", f"{dashboard_base}/availability/{key}", timeout=timeout)
    if delete_status != 403:
        print(f"[FAIL] rollup_write_denied: DELETE expected 403, got {delete_status}")
        return False
    bare_status, _ = _http("GET", f"{dashboard_base}/availability/", timeout=timeout)
    if bare_status != 404:
        print(f"[FAIL] rollup_write_denied: bare /availability/ expected 404, got {bare_status}")
        return False
    listing_status, _ = _http("GET", f"{dashboard_base}/availability/?list-type=2", timeout=timeout)
    if listing_status != 404:
        print(f"[FAIL] rollup_write_denied: bucket-listing attempt expected 404, got {listing_status}")
        return False
    print("[PASS] rollup_write_denied")
    return True


def check_bucket_anonymous_write_denied(minio_base: str, date: str, timeout: float) -> bool:
    """MinIO's anonymous download-only bucket policy refuses direct writes/deletes."""
    year, month = date[:4], date[5:7]
    json_key = f"availability/{year}/{month}/{date}.json"
    put_status, _ = _http(
        "PUT", f"{minio_base}/fleet-availability/{_PROBE_HOST}.txt", data=b"x", timeout=timeout
    )
    if put_status != 403:
        print(f"[FAIL] bucket_anonymous_write_denied: anonymous PUT expected 403, got {put_status}")
        return False
    delete_status, _ = _http("DELETE", f"{minio_base}/fleet-availability/{json_key}", timeout=timeout)
    if delete_status != 403:
        print(f"[FAIL] bucket_anonymous_write_denied: anonymous DELETE expected 403, got {delete_status}")
        return False
    print("[PASS] bucket_anonymous_write_denied")
    return True


def check_grafana_requires_login(grafana_base: str, password: str, timeout: float) -> bool:
    """Grafana refuses an unauthenticated request; an admin session sees the 3 dashboards.

    Never prints `password` — only whether it was supplied.
    """
    status, _ = _http("GET", f"{grafana_base}/api/search", timeout=timeout)
    if status != 401:
        print(f"[FAIL] grafana_requires_login: unauthenticated request expected 401, got {status}")
        return False
    if not password:
        print("[PASS] grafana_requires_login (authenticated half skipped: no --grafana-password given)")
        return True
    credentials = base64.b64encode(f"admin:{password}".encode()).decode()
    auth_status, auth_body = _http(
        "GET",
        f"{grafana_base}/api/search",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=timeout,
    )
    if auth_status != 200:
        print(f"[FAIL] grafana_requires_login: authenticated request expected 200, got {auth_status}")
        return False
    text = auth_body.decode("utf-8", errors="replace")
    missing = [
        uid
        for uid in ("fleet-host-metrics", "fleet-state-timeline", "fleet-availability")
        if uid not in text
    ]
    if missing:
        print(f"[FAIL] grafana_requires_login: dashboard search response missing uids {missing}")
        return False
    print("[PASS] grafana_requires_login")
    return True


def main() -> int:
    default_date = (datetime.now(_ROLLUP_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description=(
            "Live smoke test proving HIST-08's read-only history proxy, HIST-09's "
            "live verification of it, and HIST-10's Grafana login gate."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", required=True, help="Deployment host reachable for the dashboard/Grafana/MinIO ports")
    parser.add_argument("--dashboard-port", type=int, default=8090)
    parser.add_argument("--grafana-port", type=int, default=3000)
    parser.add_argument("--minio-port", type=int, default=9000)
    parser.add_argument(
        "--date",
        default=default_date,
        help="Rollup day to probe, YYYY-MM-DD (default: yesterday in Asia/Singapore, D-49)",
    )
    parser.add_argument(
        "--grafana-password",
        default=os.environ.get("GRAFANA_ADMIN_PASSWORD", ""),
        help="Grafana admin password; enables the authenticated half of check_grafana_requires_login",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    dashboard_base = f"http://{args.host}:{args.dashboard_port}"
    grafana_base = f"http://{args.host}:{args.grafana_port}"
    minio_base = f"http://{args.host}:{args.minio_port}"

    results: list[bool] = [
        check_ch_query_via_proxy(dashboard_base, args.timeout),
        check_ch_post_denied(dashboard_base, args.timeout),
        check_ch_write_over_get_denied(dashboard_base, args.timeout),
        check_ch_ddl_denied(dashboard_base, args.timeout),
        check_ch_system_tables_denied(dashboard_base, args.timeout),
        check_ch_credential_override_denied(dashboard_base, args.timeout),
        check_ch_other_paths_404(dashboard_base, args.timeout),
        check_rollup_json_get(dashboard_base, args.date, args.timeout),
        check_rollup_parquet_get(dashboard_base, args.date, args.timeout),
        check_rollup_write_denied(dashboard_base, args.date, args.timeout),
        check_bucket_anonymous_write_denied(minio_base, args.date, args.timeout),
        check_grafana_requires_login(grafana_base, args.grafana_password, args.timeout),
    ]

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"[SUMMARY] {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
