---
phase: 09-poller-core
fixed_at: 2026-09-09T00:58:54Z
review_path: .planning/phases/09-poller-core/09-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 9
status: partial
---

# Phase 9: Code Review Fix Report

**Fixed at:** 2026-09-09T00:58:54Z
**Source review:** .planning/phases/09-poller-core/09-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (user-requested: CR-01 and CR-02 only): 2
- Fixed: 2
- Skipped: 9 (all 7 Warning + 2 Info findings — explicitly out of user-requested scope for this run, not evaluated for applicability)

**Note on scope:** The user explicitly restricted this fix run to the 2 Critical findings (CR-01, CR-02) only, overriding this repo's default `critical_warning` fix scope. All Warning (WR-01..WR-07) and Info (IN-01, IN-02) findings from `09-REVIEW.md` were left untouched per that instruction and are listed below as skipped for that reason, not because they don't apply.

## Fixed Issues

### CR-01: Uncaught `IndexError` in `query_devices()` can crash the poll loop on a malformed row

**Files modified:** `scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`
**Commit:** `c58ab95`
**Applied fix:** In `query_devices()`, widened the `except (TypeError, ValueError)` clauses for `worst_service_state` and `scheduled_downtime_depth` to also catch `IndexError`, and wrapped the previously-unguarded `acknowledged`, `parents`, `tags`, and `filename` extractions each in their own `try/except (IndexError, TypeError)` with the same safe defaults the code already used for the "column absent" case. A row shorter than the requested column list now falls back to safe defaults (or, for the two int-parsing fields where a `continue` was already the documented behavior for other errors, is skipped) instead of raising an uncaught `IndexError` that would escape `run_forever()`'s `except LivestatusError` handler and crash the poll loop. Added `test_query_devices_survives_row_truncated_after_worst_service_state` in `tests/test_mqtt_poller.py`, which sends a row present through `worst_service_state` but missing `parents`/`tags`/`filename` and asserts it is parsed with safe defaults rather than raising.

### CR-02: Retained `lan/poller/status` stays "online" forever after a fatal startup failure

**Files modified:** `scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`
**Commit:** `1507fac`
**Applied fix:** Added a new `shutdown_mqtt_client(client)` helper (mirroring the review's suggested `_shutdown()`) that publishes `{"status": "offline"}` to `TOPIC_POLLER_STATUS` before calling `client.loop_stop()` and `client.disconnect()`. Replaced all four bare `client.loop_stop(); client.disconnect()` pairs with calls to this helper: `run_forever()`'s fatal-startup `LivestatusError` path, `run_forever()`'s existing graceful end-of-loop shutdown (refactored to reuse the same helper instead of duplicating the inline publish), and both of `main()`'s `--once` exit paths (the `LivestatusError` failure branch and the normal-completion branch). `reconcile_state()`'s separate short-lived client was left untouched — it deliberately has no LWT and publishes no birth message (per its own docstring, T-09-06), so it is outside CR-02's scope. Added `test_shutdown_mqtt_client_publishes_offline_before_disconnecting` (unit test on the new helper) and `test_run_forever_publishes_offline_status_on_fatal_startup_failure` (regression test reproducing the exact scenario described in the finding) to `tests/test_mqtt_poller.py`.

## Skipped Issues

All skipped for the same reason: **out of user-requested scope**. The user explicitly limited this fix run to CR-01 and CR-02; these findings were not evaluated for whether/how a fix would apply and remain open in `09-REVIEW.md` for a future fix run if requested.

### WR-01: `append_bounded()` / events truncation silently stop bounding when `max_entries` is `0`

**File:** `scripts/mqtt_poller.py:255-257, 781`
**Reason:** skipped (out of user-requested scope)

### WR-02: No validation on numeric env vars — a zero/negative poll interval produces a tight busy-loop

**File:** `scripts/mqtt_poller.py:116-141, 825-837`
**Reason:** skipped (out of user-requested scope)

### WR-03: `reconcile_state()`'s wait on `topology_received` does not guarantee the events payload has arrived

**File:** `scripts/mqtt_poller.py:631-698`
**Reason:** skipped (out of user-requested scope)

### WR-04: `paho-mqtt` is a main dependency of the installable `checkmk-wizard` package despite `src/` never using it

**File:** `pyproject.toml:13`
**Reason:** skipped (out of user-requested scope)

### WR-05: `check_ghost_tombstone` can permanently pollute the live retained topology if the restart command fails

**File:** `scripts/smoke_test_poller.py:342-394`
**Reason:** skipped (out of user-requested scope)

### WR-06: `--once` mode leaves a stale "online" heartbeat after it exits

**File:** `scripts/mqtt_poller.py:887-910`
**Reason:** skipped (out of user-requested scope). Note: this finding shares CR-02's root cause and its `--once` code paths were incidentally updated to use the new `shutdown_mqtt_client()` helper as part of the CR-02 fix (since CR-02's own description explicitly named these same lines as one of its two affected locations), so it is effectively resolved as a side effect. Left listed here as skipped/out-of-scope per the user's instruction rather than claimed as an intentional fix.

### WR-07: `derive_folder()` matches the *first* `"wato"` path segment, which breaks if the Checkmk site ID is itself `"wato"`

**File:** `scripts/mqtt_poller.py:282-297`
**Reason:** skipped (out of user-requested scope)

### IN-01: `keepalive=30` is duplicated across two MQTT client constructions

**File:** `scripts/mqtt_poller.py:490, 678`
**Reason:** skipped (out of user-requested scope)

### IN-02: Default credentials shipped in `deploy/compose.yaml`

**File:** `deploy/compose.yaml:22-23, 66-67, 149-150`
**Reason:** skipped (out of user-requested scope). Also noted in the source review itself as informational only / already documented, no fix required.

---

**Verification performed after both fixes:** `uv run pytest -q` → 307 passed. `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` → all checks passed (bare `ruff` binary not on `PATH` in this environment; substituted `uvx ruff check` per this phase's established convention).

_Fixed: 2026-09-09T00:58:54Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
