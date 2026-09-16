---
phase: 11-live-dashboard
plan: 01
status: paused
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
  completed: null
---

# Phase 11 Plan 01: Poller staleness + host_state_raw contract extension Summary

Extends the Phase 9 `lan/devices/{id}/status` MQTT payload with two additive fields — Checkmk's
own `staleness` value and a `host_state_raw` (`UP`/`DOWN`/`UNREACH`) field — so a dashboard
consumer can prefer Checkmk's authoritative staleness signal and separately render UNREACHABLE
hosts, without touching the existing `state` enum's meaning.

**Status: PAUSED at the Task 3 checkpoint.** Tasks 1 and 2 are complete, committed, and verified.
Task 3 is a blocking live-verification checkpoint (`gate="blocking"`) that the operator has
explicitly overridden auto-approval for — this executor did not, and must not, run the live probe
or fabricate its result. See "Checkpoint: Task 3" below for exactly what remains.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add staleness and host_state_raw to the poller | a436302 | `scripts/mqtt_poller.py` |
| 2 | Tests for the two new fields, plus the topic-contract doc update | a58abe2 | `tests/test_mqtt_poller.py`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` |

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

## Checkpoint: Task 3 (BLOCKING — not run by this executor)

**Why this executor did not run it:** Task 3 is `type="checkpoint:human-verify" gate="blocking"`.
This plan's `checkpoint_policy` explicitly states the operator has overridden auto-approval for
this checkpoint (this overrides the repo's `auto_advance: true` config default), and that the
executor must not self-approve it, fabricate a probe result, or mark it verified on its own
judgment. This sandbox also has no network route to the live `dmc` Checkmk site, so the probe
could not be run here even without the override.

**What remains:** confirm whether the live Checkmk site's Livestatus `hosts` table exposes a
`staleness` column, following the 2026-09-08/2026-09-11 dated column-probe precedent already in
`scripts/mqtt_poller.py`'s `OPTIONAL_HOST_COLUMNS` comment block.

**Exact command for the operator to run**, on the deploy host, from the repo checkout:
```bash
uv run python scripts/mqtt_poller.py --check-columns
```
(Set `LIVESTATUS_HOST`/`LIVESTATUS_PORT` env vars first if they differ from the defaults, per
the deploy doc's §7 poller smoke test.)

**What to paste back:** the full command output, plus the site's Checkmk version string (e.g.
from the Checkmk UI's "About Checkmk" page or `omd version`).

**Pass criterion:** the `staleness` line in the output reads `present: staleness (optional)`.
**Fail criterion:** it reads `missing: staleness (optional)`.

**What happens with each outcome** (to be done by whichever agent resumes this plan):
- **PRESENT:** replace the placeholder comment above the `"staleness"` entry in
  `OPTIONAL_HOST_COLUMNS` (`scripts/mqtt_poller.py`) with a dated live-verification note in the
  file's existing style — "live-verified present and populated on a real `<version>` site on
  `<date>`" — matching the 2026-09-08 and 2026-09-11 precedents already in that comment block.
  No code change is needed beyond the comment; the extraction logic already handles a present
  column correctly.
- **MISSING:** record that outcome, also dated, in the same comment block, and note that
  `staleness` stays permanently `null` on this site — a documented graceful degradation, not a
  bug. The dashboard's timestamp-age fallback (plan 11-04) then carries DASH-04 alone; no code
  change is required either way.
- **"skip" (operator declines to run it now):** record that the field is unverified and that the
  fallback path (timestamp-age against the 3× factor, D-12) carries DASH-04 until a future probe
  confirms or denies the column.

Task 3 has no code files of its own to modify beyond the one placeholder comment described
above — resuming this plan is a documentation-only edit once the probe result is known.

## Deviations from Plan

None — plan executed exactly as written for Tasks 1-2. Task 3 was correctly identified as a
blocking checkpoint per the plan's own `gate="blocking"` attribute and this execution's
`checkpoint_policy` override, and was not auto-approved.

## Self-Check

- `scripts/mqtt_poller.py` — FOUND (modified, commit a436302)
- `tests/test_mqtt_poller.py` — FOUND (modified, commit a58abe2)
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — FOUND (modified, commit a58abe2)
- Commit `a436302` — FOUND in `git log --oneline --all`
- Commit `a58abe2` — FOUND in `git log --oneline --all`

## Self-Check: PASSED
