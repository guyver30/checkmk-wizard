---
phase: 11-live-dashboard
plan: 01
status: complete
subsystem: poller
tags: [mqtt, livestatus, poller-contract, dashboard-prerequisite]
dependency-graph:
  requires: []
  provides: ["lan/devices/{id}/status.staleness", "lan/devices/{id}/status.host_state_raw"]
  affects: ["scripts/mqtt_poller.py", "tests/test_mqtt_poller.py", "docs/Podman setup for checkmk, minio, mosquitto, worker.md"]
tech-stack:
  added: []
  patterns:
    - "additive dataclass field with backward-compatible default (mirrors the existing `alias` field precedent)"
    - "per-optional-column defensive try/except in query_devices(), default on any failure, never raise mid-row"
key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
decisions: []
metrics:
  duration_minutes: null
  completed: 2026-09-16
---

# Phase 11 Plan 01: Poller staleness + host_state_raw contract extension Summary

Extends the Phase 9 `lan/devices/{id}/status` MQTT payload with two additive fields — Checkmk's
own `staleness` value and a `host_state_raw` (`UP`/`DOWN`/`UNREACH`) field — so a dashboard
consumer can prefer Checkmk's authoritative staleness signal and separately render UNREACHABLE
hosts, without touching the existing `state` enum's meaning.

**Status: COMPLETE — all 3 tasks done.** Tasks 1 and 2 were completed, committed, and verified in
a prior session. Task 3's blocking live-verification checkpoint (`gate="blocking"`) has now been
resolved: the operator ran the `--check-columns` probe on the deploy host against a real
Checkmk 2.4.0p36.cre site on 2026-09-16, confirming `staleness` is present, and this executor
recorded that dated result in the source. See "Checkpoint: Task 3" below for the full detail.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add staleness and host_state_raw to the poller | a436302 | `scripts/mqtt_poller.py` |
| 2 | Tests for the two new fields, plus the topic-contract doc update | a58abe2 | `tests/test_mqtt_poller.py`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` |
| 3 | Live `--check-columns` probe for the staleness column | ae5baa5 | `scripts/mqtt_poller.py` |

## What Was Built (Tasks 1-2)

- `OPTIONAL_HOST_COLUMNS` gained `"staleness"` as its last entry (never added to
  `REQUIRED_HOST_COLUMNS`), with a placeholder comment explicitly marked for Task 3 to replace
  with a dated live-verification note.
- `DeviceSnapshot` gained `staleness: float | None = None` and `host_state_raw: str = "UP"`,
  both defaulted so every existing construction site (including all pre-existing tests) keeps
  working unchanged.
- A new module-level `host_state_label(host_state: int) -> str` maps 0/1/2 to `UP`/`DOWN`/
  `UNREACH` (falling back to `UP` for any other value), placed immediately after
  `compute_overall_state()` with a docstring stating it does not replace that function.
  `compute_overall_state()` itself is byte-for-byte unchanged.
- `query_devices()` now derives `host_state_raw` from the already-parsed `host_state` int (no new
  column needed) and extracts `staleness` using the exact defensive shape the `alias` field
  already uses: read only when the column is present in the row index, coerce with `float(...)`,
  catch `(IndexError, TypeError, ValueError)`, default to `None` on any failure — never raises
  mid-row.
- `publish_device_status()` appends `"staleness"` and `"host_state_raw"` to the payload dict,
  placed after `"alias"` and before `"timestamp"`.
- No `--check-columns` CLI change was needed — that branch already iterates
  `OPTIONAL_HOST_COLUMNS`, so adding `"staleness"` to the tuple was the entire CLI-side change.
- No new Python dependency was added; `uv add` was never run (confirmed: `pyproject.toml` and
  `uv.lock` are absent from every commit's diff in this plan).
- Tests added: `test_host_state_label_maps_0_1_2_to_up_down_unreach`, a
  `compute_overall_state()` collapse regression guard
  (`test_compute_overall_state_down_and_unreachable_both_still_collapse_to_down`), four
  `query_devices()` staleness-defaulting tests (column absent, row truncated, non-numeric value,
  and a numeric value carried through as a float), and a
  `test_query_devices_host_state_raw_is_unreach_while_state_stays_down` test asserting both facts
  in one block. `test_publish_device_status_uses_qos0_and_exact_payload_keys` was extended with
  the two new keys.
- The doc's "### MQTT topic contract (poller)" section (§6) now lists `staleness` and
  `host_state_raw` in the `lan/devices/{id}/status` payload-keys column, plus a new paragraph
  stating each field's type, its null/degradation behavior, and explicitly that `state` never
  contains `"UNREACH"` — a consumer must read `host_state_raw` for that distinction.

## Verification Performed (Tasks 1-2)

- Task 1's exact verify command: ran, exited 0, printed `ok`.
- `grep -c 'host_state_raw' scripts/mqtt_poller.py` → `5` (≥4 required).
- `grep -n 'def host_state_label' scripts/mqtt_poller.py` → exactly one match (line 364).
- `grep -n 'return "DOWN"' scripts/mqtt_poller.py` → still matches inside `compute_overall_state`
  (line 360) — that function is unchanged.
- `uv run python scripts/mqtt_poller.py --help` → exited 0, both `--check-columns` and `--once`
  flags present, no argparse regression.
- `git diff --name-only` after Task 1 → `scripts/mqtt_poller.py` only; no `pyproject.toml` or
  `uv.lock`.
- `uv run pytest tests/test_mqtt_poller.py -q` → **98 passed** (after Task 2; 90 passed + the
  expected single failure before Task 2 extended the payload-keys test, as the plan predicted).
- `uv run pytest -q` (full repo suite) → **409 passed**, 0 failures — the wizard flow and its
  tests are untouched.
- `grep -c 'staleness' tests/test_mqtt_poller.py` → `13` (≥5 required).
- `grep -c 'host_state_raw' tests/test_mqtt_poller.py` → `5` (≥3 required).
- `grep -c 'host_state_raw' "docs/Podman setup for checkmk, minio, mosquitto, worker.md"` → `2`
  (≥1 required).
- Post-commit deletion check on both commits: `git diff --diff-filter=D --name-only HEAD~1 HEAD`
  returned empty both times — no accidental file deletions.

All of the above was actually executed and observed, not inferred from code inspection.

## Checkpoint: Task 3 (RESOLVED)

Task 3 was `type="checkpoint:human-verify" gate="blocking"` and required the operator to run the
live `--check-columns` probe on the deploy host, since this sandbox has no network route to the
live Checkmk site and the executor must not fabricate a probe result.

**Command run by the operator**, from the poller container:
```bash
podman exec mqtt-poller python -u /scripts/mqtt_poller.py --check-columns
```

**Full output:**
```
present: name (required)
present: state (required)
present: scheduled_downtime_depth (optional)
present: acknowledged (optional)
present: worst_service_state (optional)
present: parents (optional)
present: tags (optional)
present: alias (optional)
present: staleness (optional)
```

**Site version:** `omd version` reported `2.4.0p36.cre`.
**Date of probe:** 2026-09-16.
**Verdict:** PRESENT — every column the poller queries, including `staleness`, exists on the
live site.

**Resolution:** the placeholder comment above the `"staleness"` entry in `OPTIONAL_HOST_COLUMNS`
(`scripts/mqtt_poller.py`) was replaced with a dated live-verification note (commit `ae5baa5`).
The note deliberately says "present" only, not "present and populated" — `--check-columns` only
confirms the column exists in the Livestatus schema, it does not report whether the column
carries a non-null value on any given host. The timestamp-age fallback (D-12) therefore stays in
place unchanged: a present column can still return `null` per-host, so the dashboard consumer
(plan 11-04) still needs the fallback path. No extraction logic changed — `query_devices()`
already handled a present column correctly before this commit.

## Deviations from Plan

None — plan executed exactly as written for all three tasks. Task 3's checkpoint was correctly
held open (not auto-approved, not fabricated) until the operator supplied the real probe output,
then closed out with a documentation-only edit as the plan specified.

## Self-Check

- `scripts/mqtt_poller.py` — FOUND (modified, commits a436302, ae5baa5)
- `tests/test_mqtt_poller.py` — FOUND (modified, commit a58abe2)
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — FOUND (modified, commit a58abe2)
- Commit `a436302` — FOUND in `git log --oneline --all`
- Commit `a58abe2` — FOUND in `git log --oneline --all`
- Commit `ae5baa5` — FOUND in `git log --oneline --all`
- `uv run pytest -q` after the Task 3 edit — 409 passed, 0 failures (comment-only change did not
  alter the suite)

## Self-Check: PASSED
