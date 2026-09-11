---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 01
status: complete
subsystem: checkmk-rest-shape-probing
tags: [checkmk, rest-api, livestatus, device-type, tag-group, probe-script]
dependency-graph:
  requires: []
  provides:
    - "device_types.json (D-05 device-type choice list, 'other' first per D-06)"
    - "scripts/probe_checkmk_rest_shapes.py (stdlib REST/Livestatus shape probe, live-verified 2026-09-11)"
    - "Live-confirmed tag-group POST body shape (`id`, not `ident`)"
    - "Live-confirmed `extensions.folder` presence and shape on host_config entries"
    - "Live-confirmed that a tag group's default does not materialise as an explicit host attribute"
  affects:
    - "10-02 (tag-group creation implementation — backfill counting rule now known: count hosts LACKING an explicit tag_device_type attribute, not hosts equal to 'other')"
    - "10-03 (poller folder derivation implementation — must implement Pattern 3 Candidate A only; no folder_config link fallback exists on this site)"
    - "10-06 (must re-run probe_livestatus_tags_keys after the wizard sets a real device_type tag, to fully close Assumption A3)"
tech-stack:
  added: []
  patterns:
    - "Single-choke-point REST helper returning (status_code, parsed_body) rather than raising on non-2xx, mirroring mqtt_poller.py's _livestatus_request normalization shape"
key-files:
  created:
    - device_types.json
  modified:
    - scripts/probe_checkmk_rest_shapes.py
decisions: []
metrics:
  duration: "Task 1: 2026-09-11 (prior session); Task 2 (live run): 2026-09-11; Task 3: 2026-09-11"
  completed: "2026-09-11"
---

# Phase 10 Plan 01: Checkmk REST/Livestatus Shape Probe Summary

One-liner: Ran the checked-in REST/Livestatus shape probe against a live Checkmk 2.4.0p35
CE site and recorded its findings — tag-group POST accepts `id` (not `ident`),
`extensions.folder` exists with no link-based fallback, and a tag group's default does not
materialise as an explicit host attribute — closing Assumptions A1 and A2 and partially
closing A3.

## What Was Completed

### Task 1 (prior session, commit `1460421`)

`device_types.json` (repo root, `other` first per D-06) and
`scripts/probe_checkmk_rest_shapes.py` (stdlib-only diagnostic covering P1-P6). See prior
summary content for full detail; unchanged in this session.

### Task 2 — live probe run (2026-09-11)

The operator ran the probe from inside the `automation-worker` container against REST base
`http://checkmk:5000/dmc/check_mk/api/1.0`, site `dmc`, Checkmk 2.4.0-latest (check-mk-raw).
Full verbatim output was reviewed. Verdicts observed:

- **P1** (`probe_real_group_absent`): status 404 — the real `device_type` group does not
  exist yet, as expected.
- **P2** (`probe_tag_group_create_shape`): the `id`-shape POST was accepted on the first
  attempt, HTTP 200. No `ident` retry was needed. Accepted top-level body keys: `id`,
  `title`, `tags` (each tag entry: `id`, `title`, `aux_tags: []`). The site's response
  additionally carried `extensions.topic: "Tags"`, defaulted by Checkmk even though this
  probe never sent a `topic` key.
- **P3** (`probe_tag_group_readback`): GET of the created group round-tripped the same
  `id`/`title`/`tags` shape, status 200.
- **P4** (`probe_host_config_folder_shape`): status 200. `extensions.folder` is present,
  observed value `'/folder2'` (plain `str`, leading slash, no trailing slash) for host
  `192.168.0.1`. No `folder_config` link href was found in the entry's `links` array.
  `extensions.attributes` for that host contained only `['ipaddress', 'meta_data',
  'tag_agent', 'tag_snmp_ds']` — no `tag_gsd_probe_device_type` key appeared even though the
  probe group's default tag (`other`) was implicitly in effect.
- **P5** (`probe_livestatus_tags_keys`): all three sampled hosts (`test-machine`,
  `checkmk_wizard`, `192.168.0.67`) returned bare (unprefixed) `tags` keys — `agent`,
  `snmp_ds`, `criticality`, `ip-v4`, `networking`, `piggyback`, `ping`, `site`,
  `address_family`. No host carried a `device_type`/`tag_device_type` tag at probe time, so
  this is inference from sibling tag groups, not direct observation of that specific key.
- **P6** (`cleanup_probe_tag_group`): DELETE returned 204; the throwaway
  `gsd_probe_device_type` group was removed. The operator confirmed no secret appeared
  anywhere in the pasted output.

### Task 3 — recorded findings (commit `258fa10`)

Replaced the probe script's `Findings: not yet run against a live site` placeholder with a
dated `Live-verified against a real Checkmk 2.4.0p35 CE site on 2026-09-11` block recording,
in prose, exactly what Task 2's run reported for A1, A2, and A3 (see the four bullets below
and the docstring itself for full text). No contradiction between RESEARCH.md's prediction
and the live result was found for A1's key spelling — `id` was correctly predicted as the
accepted shape. RESEARCH.md's candidate body additionally listed a `topic` key; the live run
showed this key is not required (Checkmk defaults it), which is recorded as a minor
correction, not treated as a contradiction requiring a script fix, since omitting an optional
key does not change behavior downstream plans depend on.

## Findings closing RESEARCH.md's Assumptions Log

1. **A1 (tag-group POST body shape) — CONFIRMED.** `id` (not `ident`) is the correct
   top-level key, both at the group level and inside each `tags[]` entry. HTTP 200 on first
   attempt.
2. **A2 (`extensions.folder` on host_config) — CONFIRMED, Candidate A only.**
   `extensions.folder` exists as a plain string (`'/folder2'` observed). No `folder_config`
   link href exists anywhere in the host_config entry's `links` array on this site/version —
   Pattern 3 Candidate B is not available. **Plan 10-03 must implement Candidate A
   exclusively; there is no fallback link to consult.**
3. **Tag-group default materialization — NOT an explicit attribute.** A newly created tag
   group's implicit first-tag default (`other`) does not appear as an explicit
   `tag_<group_id>` key in `extensions.attributes`. **Consequence for plan 10-02:** its
   backfill count (D-08, "how many hosts that default touched") cannot be obtained by
   counting hosts whose `tag_device_type` attribute equals `other`, because no such attribute
   is ever written by the default. Plan 10-02 must instead count hosts LACKING an explicit
   `tag_device_type` attribute entirely. This is flagged here as a finding for plan 10-02 to
   reckon with; 10-02-PLAN.md itself was not modified by this plan.
4. **A3 (Livestatus tags key shape) — PARTIALLY CONFIRMED.** Sampled hosts' `tags` dict keys
   are bare (unprefixed): `agent`, `snmp_ds`, `criticality`, etc. — not `tag_`-prefixed. By
   inference from these sibling tag groups, `device_type` is expected to follow the same bare
   shape. However, no host carried a `device_type` tag at probe time, so this is strong
   inference, not direct observation of that specific key. **A3 is not fully closed; plan
   10-06 re-runs `probe_livestatus_tags_keys` after the wizard has set a real device-type tag
   to confirm it directly.**

## Deviations from Plan

None — Tasks 1-3 executed as written. No Rule 1-4 deviations were needed. The only departure
from RESEARCH.md's prediction (the `topic` key in the POST body) is not a bug or gap in the
probe script — the script's `id`-shape body already omitted `topic` and succeeded, so no code
change was needed; this is recorded purely as a docstring correction to RESEARCH.md's
candidate shape.

## Deferred to Downstream Plans (not decided or implemented here)

- Plan 10-02: adopt the "count hosts lacking an explicit `tag_device_type` attribute"
  backfill-counting rule (finding 3 above).
- Plan 10-03: implement Pattern 3 Candidate A (`extensions.folder`) only; no Candidate B
  fallback path exists on this site.
- Plan 10-06: re-run `probe_livestatus_tags_keys` after a real `device_type` tag exists on at
  least one host, to fully close Assumption A3.

## Self-Check

- `[ -f device_types.json ]` → checked below
- `[ -f scripts/probe_checkmk_rest_shapes.py ]` → checked below
- `git log --oneline --all | grep -q 1460421` → checked below
- `git log --oneline --all | grep -q 258fa10` → checked below

## Self-Check: PASSED
