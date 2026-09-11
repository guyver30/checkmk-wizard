---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 01
status: paused-at-checkpoint
subsystem: checkmk-rest-shape-probing
tags: [checkmk, rest-api, livestatus, device-type, tag-group, probe-script]
dependency-graph:
  requires: []
  provides:
    - "device_types.json (D-05 device-type choice list, 'other' first per D-06)"
    - "scripts/probe_checkmk_rest_shapes.py (stdlib REST/Livestatus shape probe, not yet run live)"
  affects:
    - "10-02 (tag-group creation implementation — blocked on this plan's live-verified findings)"
    - "10-03 (poller folder derivation implementation — blocked on this plan's live-verified findings)"
tech-stack:
  added: []
  patterns:
    - "Single-choke-point REST helper returning (status_code, parsed_body) rather than raising on non-2xx, mirroring mqtt_poller.py's _livestatus_request normalization shape"
key-files:
  created:
    - device_types.json
    - scripts/probe_checkmk_rest_shapes.py
  modified: []
decisions: []
metrics:
  duration: "partial — Task 1 complete, Task 2 (checkpoint) blocking, Task 3 not started"
  completed: "2026-09-11 (Task 1 only)"
---

# Phase 10 Plan 01: Checkmk REST/Livestatus Shape Probe Summary

**Status: PAUSED at Task 2's blocking human-verify checkpoint.** Task 1 is complete and
committed. Task 2 requires running the probe script against a real, live Checkmk 2.4.0p35
CE site — this development environment has no podman, no broker, and no Checkmk site, so
the run cannot be simulated, fabricated, or skipped. Task 3 (recording the live findings as
a dated citation block) has not started and depends entirely on Task 2's real output.

One-liner: Added the checked-in `device_types.json` choice list and a stdlib-only,
self-cleaning REST/Livestatus probe script that still needs to be run against a live site
before its findings can be recorded.

## What Was Completed (Task 1)

- **`device_types.json`** (repo root): a JSON array of exactly 6 strings, `other` first —
  `["other", "E-link", "ACS", "Multimedia", "NetworkDevice", "GroupController"]` — per D-05
  (config-file-driven choice list) and D-06 (`other` must be first so Checkmk's tag-group
  creation auto-defaults every pre-existing host safely).
- **`scripts/probe_checkmk_rest_shapes.py`** (stdlib-only: `urllib.request`, `json`, `socket`,
  `os`, `argparse`, `pathlib` — no `httpx`/`paho`/`requests`): a diagnostic that will answer
  Assumptions A1/A2/A3 from `10-RESEARCH.md` in a single run:
  - **P1** `probe_real_group_absent` — GETs `/objects/host_tag_group/device_type`, expects 404.
  - **P2** `probe_tag_group_create_shape` — POSTs a throwaway `gsd_probe_device_type` tag group
    using the Checkmk >=2.4.0 `id`-keyed shape first, retrying with the pre-2.4.0 `ident`-keyed
    shape on 4xx, and prints an explicit verdict naming which spelling was accepted.
  - **P3** `probe_tag_group_readback` — GETs the created group back to record its round-trip shape.
  - **P4** `probe_host_config_folder_shape` — GETs `/domain-types/host_config/collections/all`,
    inspects the first host's `extensions.folder` field (Pattern 3 Candidate A), whether
    `extensions.attributes` gained a `tag_gsd_probe_device_type` key (answers whether Checkmk
    materialises a new tag group's default as an explicit host attribute or leaves it implicit),
    and prints every `folder_config` link href (Pattern 3 Candidate B fallback).
  - **P5** `probe_livestatus_tags_keys` — opens a raw TCP socket to Livestatus, samples up to 3
    hosts' `tags` dict key shapes (bare vs `tag_`-prefixed).
  - **P6** `cleanup_probe_tag_group` — DELETEs the throwaway group in a `finally` block so it runs
    even if P3-P5 raise, leaving the live site unchanged; prints a loud `[FAIL]` naming the group
    to remove by hand if the delete doesn't return 200/204.
  - The auth header is always rendered redacted (`Bearer <username> ***`); `CMK_REST_SECRET`/
    `CMK_REST_USERNAME` are never printed. Missing credentials exit non-zero with a message
    naming the specific missing variable.

### Verification performed for Task 1 (all commands actually run, not inferred)

- `uv run python -c "import json,pathlib; c=json.loads(...); assert c[0]=='other' and len(c)==6"` — passed.
- `uv run python scripts/probe_checkmk_rest_shapes.py --help` — exit 0, lists `--rest-host`,
  `--rest-port`, `--site-id`, `--rest-username`, `--rest-secret`, `--livestatus-host`,
  `--livestatus-port`, `--timeout`.
- `python3 -c "import ast; ast.parse(...)"` — exit 0 (valid syntax).
- `grep -v '^#' scripts/probe_checkmk_rest_shapes.py | grep -c 'import httpx\|import paho\|import requests'` — returned `0` (stdlib only, confirmed).
- Literal-presence greps for `gsd_probe_device_type` (12 occurrences), `/domain-types/host_tag_group/collections/all` (2), `/domain-types/host_config/collections/all` (3), `extensions` (12), `folder_config` (6), `OutputFormat: json` (1) — all present.
- `grep -n 'id.*"device_type"' scripts/probe_checkmk_rest_shapes.py` — no match (exit 1), confirming the script never POSTs the literal `device_type` id.
- Ran the script with `CMK_REST_USERNAME`/`CMK_REST_SECRET` unset — exited 1, printed
  `[FAIL] CMK_REST_USERNAME is not set (env var or --rest-username)`; with username set but
  secret unset — exited 1, printed `[FAIL] CMK_REST_SECRET is not set (env var or --rest-secret)`.
- `uv run ruff check scripts/probe_checkmk_rest_shapes.py` — all checks passed (verified with
  a temporary WIP-free stash-and-restore to confirm 7 ruff findings elsewhere in `src/`/`tests/`
  are pre-existing on the base commit, not introduced by this plan — out of scope per the
  Scope Boundary rule, not fixed here).
- `uv run pytest -q` — 307 passed, 0 failed (no regression from adding these two new files).

Commit: `1460421` — `feat(10-01): add device_types.json and Checkmk REST/Livestatus shape probe`

## What Is NOT Yet Done

- **Task 2** (`checkpoint:human-verify`, `gate="blocking"`): the probe script has never been
  run against a real Checkmk site. Nothing in this summary should be read as confirming
  Assumptions A1/A2/A3 — they remain open until a human runs the script on the deployment
  host and reports the verbatim output.
- **Task 3**: the module docstring's `Findings: not yet run against a live site — see
  10-01-PLAN.md Task 3` placeholder is still in place in the committed script and must not be
  replaced until Task 2's real output is available.

## Deviations from Plan

None — Task 1 executed as written. No Rule 1-4 deviations were needed.

## Self-Check

- `[ -f device_types.json ]` → FOUND
- `[ -f scripts/probe_checkmk_rest_shapes.py ]` → FOUND
- `git log --oneline --all | grep -q 1460421` → FOUND

## Self-Check: PASSED
