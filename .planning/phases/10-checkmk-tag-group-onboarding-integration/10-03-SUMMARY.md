---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 03
status: complete
subsystem: mqtt-poller
tags: [poller, rest-api, livestatus, folder-derivation, alias, checkmk]
dependency-graph:
  requires: ["10-01"]
  provides:
    - "alias field end-to-end in DeviceSnapshot, publish_device_status payload, and topology nodes/signature (D-10)"
    - "RestError, cmk_rest_base_url(), fetch_host_folders() -- stdlib urllib.request REST folder-lookup helper"
    - "PollerConfig REST credential fields (cmk_rest_host/port, cmk_site_id, cmk_rest_username, cmk_rest_secret) with the secret redacted in __repr__"
    - "query_devices()'s folders keyword parameter replacing derive_folder()'s filename-string parsing"
    - "run_forever()'s per-cycle REST folder refresh with last-known-good reuse on RestError"
  affects:
    - "10-05 (compose.yaml must wire CMK_REST_USERNAME/CMK_REST_SECRET into the poller service's environment; this plan's poller degrades gracefully with empty defaults until then)"
    - "10-06 (live run must confirm the alias column is actually present on 2.4.0p35, and re-run probe_livestatus_tags_keys to close A3)"
tech-stack:
  added: []
  patterns:
    - "Single-choke-point REST helper (fetch_host_folders) mirroring _livestatus_request's error-normalization shape, using stdlib urllib.request rather than httpx"
    - "Per-cycle enrichment degradation: a RestError degrades one field (folder) for one cycle rather than skipping the cycle, distinct from the mandatory Livestatus query's skip-cycle-on-error shape"
key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
decisions:
  - "D-10 field name kept as 'folder' (not renamed to 'location'/'group') -- the Phase 9 contract already publishes it generically with no VLAN semantics; renaming would strand every retained payload on the broker for zero semantic gain."
  - "REST client is stdlib urllib.request, not httpx -- the module docstring's 'standalone, dependency-light' constraint makes a second pip-installed HTTP client for one authenticated GET unjustified."
  - "Only Pattern 3 Candidate A (extensions.folder) is implemented -- 10-01's live probe found no folder_config link href on the real site, so no fallback path exists or is coded."
  - "A REST failure reuses the last known good folder map rather than falling back to an empty dict, to keep topology_signature stable across a transient REST blip (PLR-04)."
metrics:
  duration: "Task 1-3: 2026-09-11 (single session)"
  completed: "2026-09-11"
---

# Phase 10 Plan 03: MQTT Poller Alias & REST Folder Association Summary

One-liner: Extended the standalone MQTT poller so every published device carries its Checkmk
alias and its location/group label from Checkmk's own REST-computed folder association
(`extensions.folder`) instead of parsing the OMD `filename` path, closing WR-07/Pitfall 10 at
the root with a stdlib `urllib.request` REST client that degrades gracefully on failure.

## What Was Completed

### Task 1 — Alias end-to-end (commit `89558c2`)

Added `"alias"` to `OPTIONAL_HOST_COLUMNS`, `alias: str = ""` to `DeviceSnapshot`, defensive
`alias` extraction in `query_devices` (coercing a non-string or missing/truncated value to
`""`), `"alias"` in `publish_device_status`'s payload, `"alias"` in each `topology_nodes` node,
and `alias` in `topology_signature`'s per-node tuple so an alias rename triggers a topology
republish. Extended existing `query_devices` fixtures and added dedicated alias tests; updated
every hand-crafted topology-node dict literal in the test file to carry the new `"alias"` key
(required because `topology_signature`/`parse_topology_payload` now index it unconditionally).
69 tests passed after this task.

### Task 2 — RestError, fetch_host_folders, PollerConfig REST credentials (commit `0a783ca`)

Added stdlib `urllib.request`/`urllib.error` imports, `class RestError(RuntimeError)`,
`cmk_rest_base_url(config)` (replicates `api.py`'s `_site_base()` construction without
importing `checkmk_wizard`), and `fetch_host_folders(base_url, username, secret, timeout)` — a
single choke point mirroring `_livestatus_request`'s pattern: one `try` wrapping the request
and JSON decode, catching `HTTPError`/`URLError`/`OSError`/`TimeoutError`/`JSONDecodeError`,
re-raising `RestError` with a message naming only the URL and underlying error (never the
Authorization header, username, or secret — T-10-10). Per-entry parsing is defensive: a
non-dict entry or one missing `id` is skipped with `_logger.debug`; a missing folder field maps
to `""`. Extended `PollerConfig` with `cmk_rest_host`/`cmk_rest_port`/`cmk_site_id`/
`cmk_rest_username`/`cmk_rest_secret` (all with safe defaults, appended after `log_level`), and
extended the hand-written `__repr__` to render `cmk_rest_secret` as `'***'` while the other four
render in the clear. `from_env()` reads `CMK_REST_HOST`/`CMK_REST_PORT`/`CMK_SITE_ID`/
`CMK_REST_USERNAME`/`CMK_REST_SECRET`, reusing the exact `CMK_SITE_ID` name
`deploy/compose.yaml`'s `checkmk`/`worker` services already set. 77 tests passed after this
task, including a 401-response test asserting the raised `RestError`'s message contains neither
the username nor the secret.

### Task 3 — Replace filename-string derivation with the REST folder map (commit `095fa55`)

Deleted `derive_folder()` and removed `"filename"` from `OPTIONAL_HOST_COLUMNS`, leaving a dated
(`Bug fixed 2026-09-11`) post-mortem comment above the column constants naming WR-07 and
Pitfall 10 and explaining that `filename` was confirmed present by Phase 9's probe but is
deliberately no longer consumed. `query_devices` gained a keyword-only `folders: dict[str, str]
| None = None` parameter; the row loop now does `folders.get(name, "") if folders else ""`
instead of calling `derive_folder`. `run_forever` computes `cmk_rest_base_url(config)` once,
initializes `last_folders: dict[str, str] = {}`, and inside each cycle attempts
`fetch_host_folders(...)` before `query_devices`: on success it overwrites `last_folders`, on
`RestError` it logs a warning and **reuses** `last_folders` unchanged (commented as deliberate —
blanking every folder on a transient REST failure would publish a spurious topology change via
`topology_signature`, then another when REST recovered, violating PLR-04). The REST fetch is
enrichment, not the poller's core duty, so a `RestError` here never skips the cycle the way a
`LivestatusError` from the mandatory Livestatus query does. Added
`DEFAULT_REST_PORT`/`DEFAULT_REST_TIMEOUT_SECONDS` module constants. Deleted the two
`derive_folder` tests, removed `filename` from every `columns` fixture, added a WR-07 regression
test (`test_query_devices_wr07_site_named_wato_produces_correct_folder`) asserting the REST
mapping is immune to a site id of `wato`, and added `run_forever` tests covering: REST failure
reuses the last known good map across a second cycle, and a REST fetch that has never succeeded
leaves `folders={}` while `run_cycle` still executes. Full suite: 322 tests passed;
`scripts/mqtt_poller.py`/`tests/test_mqtt_poller.py` are ruff-clean.

## Live-Verified Findings Consumed (from 10-01)

- `extensions.folder` is the only viable folder source (Pattern 3 Candidate A) — no
  `folder_config` link href exists on the live site, so `fetch_host_folders` implements
  Candidate A exclusively and does not include a link-following fallback, per the deviation
  noted below.
- `extensions.folder` carries a leading slash and no trailing slash (observed `'/folder2'`) —
  `fetch_host_folders` strips the leading slash so the mapped value matches the `a/b` segment
  shape `derive_folder()` used to produce, avoiding a downstream contract change.
- The Livestatus bare-tags-key assumption (A3) is not touched by this plan (it governs
  `extract_device_type`, not folder derivation) and remains open for 10-06.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Existing `run_forever` tests would have made real network calls**

- **Found during:** Task 3
- **Issue:** The pre-existing `test_run_forever_survives_livestatus_error_and_does_not_raise`
  and `test_run_forever_publishes_offline_status_on_fatal_startup_failure` tests did not mock
  `fetch_host_folders`, and `run_forever` now calls it every cycle before `query_devices`.
  Without a mock, the first test would attempt a real `urlopen` against `http://checkmk:5000/...`
  from the test environment, which has no such host reachable — this would not crash the test
  (the `RestError` is caught) but would silently redirect real, un-sandboxed network I/O out of
  a unit test.
- **Fix:** Added `patch.object(poller, "fetch_host_folders", return_value={})` to the
  `LivestatusError`-survival test. The fatal-startup-failure test never reaches the REST fetch
  (it fails at the column probe, before the loop), so it needed no change.
- **Files modified:** `tests/test_mqtt_poller.py`
- **Commit:** `095fa55`

### Plan Prose vs. Live-Verified Findings

**2. [Rule 1 - Correction] No `folder_config` link-href fallback implemented**

10-03-PLAN.md's Task 2 action text describes extracting the folder via "whichever source plan
10-01's probe confirmed: `extensions.folder` if present (Pattern 3 Candidate A), otherwise the
tilde-encoded folder id parsed out of the `folder_config` link href (Candidate B)". Per the
`<live_verified_findings_from_10_01>` block in this plan's own invocation and 10-01-SUMMARY.md
finding 2, the probe found **no** `folder_config` link href anywhere in the host_config entry's
`links` array on the real site — Candidate B does not exist to fall back to. `fetch_host_folders`
therefore implements Candidate A only, with no dead fallback branch. This is documented in the
function's own live-verification comment rather than silently omitted.

No other deviations. No Rule 4 (architectural) decisions were needed — every change was an
additive extension of an existing analog pattern already proven in this file
(`_livestatus_request`'s choke-point shape, the existing optional-column defensive-parse shape,
`PollerConfig`'s redacted-repr convention).

## Credential Handling (10-05 dependency)

Per the plan's `<credential_context>`, `PollerConfig.cmk_rest_username`/`cmk_rest_secret` default
to `""` when `CMK_REST_USERNAME`/`CMK_REST_SECRET` are unset (as they currently are in the
`automation-worker` container). `fetch_host_folders` is called unconditionally every cycle
regardless of whether credentials are present; with empty credentials the real Checkmk site
would return 401, `fetch_host_folders` raises `RestError`, and `run_forever` logs a warning and
reuses `last_folders` (`{}` until a later cycle with real credentials succeeds) — the poller
never crashes or stalls for lack of REST credentials. No change to `deploy/compose.yaml` was
made (explicitly out of scope for this plan; that wiring is 10-05's job).

## Self-Check

- `[ -f scripts/mqtt_poller.py ]`
- `[ -f tests/test_mqtt_poller.py ]`
- `git log --oneline --all | grep -q 89558c2`
- `git log --oneline --all | grep -q 0a783ca`
- `git log --oneline --all | grep -q 095fa55`
- `uv run pytest tests/test_mqtt_poller.py -q` → 80 passed
- `uv run pytest -q` (full suite) → 322 passed
- `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` → All checks passed
- `grep -c 'def derive_folder' scripts/mqtt_poller.py` → 0
- `grep -c '"filename"' scripts/mqtt_poller.py` → 0
- `src/checkmk_wizard/api.py`, `src/checkmk_wizard/wizard.py`, `tests/test_api.py`,
  `tests/test_wizard.py` — untouched by this plan's commits (verified via `git diff --stat`
  on each of the three commits above)

## Known Pre-Existing Condition (Not This Plan's Scope)

`uvx ruff check scripts/ src/ tests/` (the full-repo invocation from this plan's `<verification>`
block) reports 7 pre-existing errors, all in `tests/test_wizard.py` (e.g. `SIM117`/`RET501`/
`PLR1711` style findings unrelated to this plan's changes). `tests/test_wizard.py` is explicitly
out of scope for this parallel executor (owned by concurrently-running plan 10-02) and was not
modified by any commit in this plan — confirmed via `git diff` showing no changes to that file
across all three commits. `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py`
(this plan's actual files) passes cleanly.

## Self-Check: PASSED
