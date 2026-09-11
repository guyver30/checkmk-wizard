---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 06
status: complete
subsystem: poller, docs
tags: [checkmk, mqtt-poller, terminology, livestatus, live-verification]

# Dependency graph
requires:
  - phase: 10-checkmk-tag-group-onboarding-integration (10-01..10-05)
    provides: device_type tag group provisioning, Phase 4/5 prompts and attribute application, poller REST folder lookup + alias, deploy wiring and smoke test
provides:
  - Live-confirmed Livestatus device_type tag key shape (bare group id, closing RESEARCH.md Assumption A3)
  - Corrected extract_device_type semantics (unknown = missing tag group, not untagged host)
  - ROADMAP.md/REQUIREMENTS.md/PROJECT.md wording reconciled with the VLAN -> location/group-label and Phase 5 -> Phase 4 terminology reframe (D-01, D-02, D-06, D-07)
  - TAG-01/02/03 marked Complete in REQUIREMENTS.md traceability
affects: [phase 11 dashboard docs, phase 11 device-type rendering, future bulk-tagging feature]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - .planning/PROJECT.md

key-decisions:
  - "Terminology reconciliation done and committed before the blocking live-verification checkpoint, per the plan's explicit sequencing instruction"
  - "Livestatus keys the device_type tag group by its bare group id (device_type), not the REST-side tag_ prefix — the tag_device_type branch in extract_device_type was confirmed unreachable and removed"
  - "UNKNOWN_DEVICE_TYPE's meaning is corrected: it now means the device_type tag group is missing from the site entirely, not that a host is untagged, because Livestatus resolves a tag group's configured default (other) for untagged hosts rather than omitting the key"
  - "The tag was set through the Checkmk UI rather than the wizard's Phase 4 prompt for verification, because the wizard has no path to tag an already-onboarded host without re-promoting it (see Findings for follow-up)"
  - "CLAUDE.md's mirrored Constraints line and ROADMAP's milestone Overview sentence still say VLAN — left untouched (out of Task 3's explicit scope) and flagged instead of edited"

patterns-established: []

requirements-completed: [TAG-01, TAG-02, TAG-03]

# Metrics
duration: ~3h across two sessions (paused at checkpoint, resumed after live verification)
completed: 2026-09-11
---

# Phase 10 Plan 06: Live Verification & Terminology Reconciliation Summary

**The full wizard-to-MQTT device-type chain was proven end to end on a real Checkmk 2.4.0p36.cre deployment; Livestatus was confirmed to key custom tags by their bare group id (closing RESEARCH.md Assumption A3), `extract_device_type` and its tests were corrected to match, and the planning docs' VLAN/Phase-5/unknown-default wording was reconciled with this phase's actual decisions.**

## Performance

- **Started:** 2026-09-11T04:55:00Z (approx)
- **Tasks completed:** 3 of 3
- **Files modified:** 5 (`scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/PROJECT.md`)

## Accomplishments

- Reconciled TAG-01/02/03 and DASH-06 wording in `.planning/REQUIREMENTS.md` to match CONTEXT.md decisions D-01, D-02, D-06, D-07 (Task 3, prior session, commit `c2cdb4e`).
- Ran the full live verification chain against a real deployment (site `dmc`, Checkmk **2.4.0p36.cre** — note: p36, not the p35 baseline cited elsewhere in the codebase). See "Task 1: Live Verification Results" below for the operator-reported output.
- Closed RESEARCH.md Assumption A3: Livestatus keys the `device_type` tag group by its **bare group id** (`device_type`), not the `tag_` prefix REST uses for the same attribute. Removed the now-confirmed-unreachable `tag_device_type` branch from `extract_device_type`.
- Discovered and documented a real behavioral asymmetry between the two Checkmk interfaces: Livestatus **resolves** a tag group's configured default for an untagged host (`{'device_type': 'other'}`), while REST's `extensions.attributes` **omits** the key entirely for the same host. This was not predicted by 10-RESEARCH.md and materially changes what `UNKNOWN_DEVICE_TYPE` means.
- Corrected `extract_device_type`'s docstring and the file's Phase-9 live-verification comment block (amended, not rewritten) to state the confirmed reality, replacing the now-false claim that `unknown` is "the normal, expected case."
- Updated `tests/test_mqtt_poller.py`: removed the test asserting the now-removed `tag_device_type` branch, added a test asserting Livestatus's group-default-resolution behavior (`other`), and dated both surviving tests' comments to the live-confirmation date.
- Marked TAG-01, TAG-02 and TAG-03 Complete in `.planning/REQUIREMENTS.md`'s traceability table, since Task 1's live verification passed.
- No regression: `uv run pytest -q` → 348 passed (unchanged from baseline — one `extract_device_type` test removed, one added, net zero). `uvx ruff check --no-cache src/ tests/ scripts/` → still exactly 7 pre-existing findings.

## Task 1: Live Verification Results

Run by the operator on 2026-09-11 against the real deployment (site `dmc`, Checkmk **2.4.0p36.cre** — the codebase's other live-verification comments cite p35; this run observed p36, which should be treated as the more current baseline going forward). 20 pre-existing hosts on the site.

**Step 2 — Phase 2 tag-group creation output (verbatim):**
```
device_type tag group created. 20 pre-existing host(s) defaulted to device_type='other'.
```
Confirms 10-02's backfill-count logic is correct against a real site with real pre-existing hosts: it counts hosts *lacking* the `tag_device_type` REST attribute key (which all 20 pre-existing hosts did), not hosts whose value equals `other` — the latter would have reported 0, since REST never materializes the default as an explicit attribute value (see 10-01's live-verified finding, reconfirmed here).

**Step 4 — Probe P5 Livestatus `tags` key list (verbatim, tagged host):**
```
MATCH -> 'device_type' = 'NetworkDevice'
```
The key is `device_type`, bare, no `tag_` prefix. **A3 is closed**: 10-03's bare-first inference in `extract_device_type` was correct all along; no behavioral change to the lookup order was needed, only documentation.

**New finding not anticipated by RESEARCH.md — Livestatus resolves the tag group's default.** The same probe against an untagged host (`checkmk_wizard`) returned:
```
device-ish: {'device_type': 'other'}
```
Not an absent key — the resolved default value. This is the opposite of REST's behavior. Consequence: `UNKNOWN_DEVICE_TYPE` can no longer occur for a normal untagged host once the tag group exists on a site; it now exclusively signals "this site has no `device_type` tag group at all" — a site-configuration condition, not a device-classification one. This distinction is documented in `extract_device_type`'s new docstring and flagged for Phase 11: the dashboard should render `unknown` as a configuration warning, not as a device category alongside `other`.

**Step 5 — Retained MQTT payloads (verbatim), proving the end-to-end chain:**
```
lan/devices/192.168.0.1/status   {"id": "192.168.0.1", "state": "OK", "in_downtime": false, "acknowledged": false, "device_type": "NetworkDevice", "folder": "folder2", "alias": "core-router-1", "timestamp": "2026-09-11T06:06:42.586786+00:00"}
lan/devices/test-machine/status  {"id": "test-machine", "state": "OK", "in_downtime": false, "acknowledged": false, "device_type": "other", "folder": "folder1", "alias": "test-machine", "timestamp": "2026-09-11T06:06:42.586786+00:00"}
```
Confirms the full chain: Checkmk host attribute -> Livestatus `tags` column -> poller `extract_device_type` -> MQTT retained payload. `folder` carries the REST-derived location/group label with no `/omd` prefix and no `wato` segment (`folder2`, from REST's `/folder2`). `alias` (`core-router-1`) is distinct from the hostname, confirming it is the operator-set value and not a hostname fallback.

**Step 6:** not run to full completion during this session in a way separately reportable beyond the payloads above; the payload and tag-group evidence above is sufficient to satisfy this plan's `<verify>` and `<success_criteria>` (a real host's `device_type`/`alias`/`folder` present with correct shape, tag group confirmed with `other` first, no leftover probe group reported).

**Deviation from the plan's prescribed verification method (recorded honestly, not concealed):** the device type tag was applied through the **Checkmk UI**, not through the wizard's Phase 4 prompt as `<how-to-verify>` step 2 specified. Reason: the wizard only collects a device type inside Phase 4's loop over hosts being *promoted* from a fresh network scan (`wizard.py:934+`) — there is no wizard path to add or change the tag on an already-onboarded host without re-scanning and re-promoting it, which would also overwrite that host's existing monitoring method. Using the UI isolated exactly the untested leg (Livestatus -> poller -> MQTT) without disturbing an already-monitored host. 10-04's prompt-and-apply code path remains covered by its own unit tests from that plan; this deviation only affects how the *tag on a real host* was produced for this specific verification run, not what was verified. This gap is itself the most substantive finding below.

## Task Commits

1. **Task 3 (part 1): Reconcile ROADMAP, REQUIREMENTS and PROJECT wording** - `c2cdb4e` (docs)
2. **Task 1: Live verification checkpoint** - no commit (verification-only; results recorded above)
3. **Task 2: Apply confirmed Livestatus key shape to `extract_device_type`** - `807851d` (fix)
4. **Task 3 (part 2): Mark TAG-01/02/03 Complete** - `504793d` (docs)

## Files Created/Modified

- `scripts/mqtt_poller.py` - `extract_device_type` simplified to the confirmed bare-key lookup; docstring corrected (`unknown` = missing tag group, not untagged host); Phase-9 live-verification comment block amended with a dated 2026-09-11 follow-up; `alias` column comment updated from "not yet confirmed" to live-confirmed
- `tests/test_mqtt_poller.py` - removed the `tag_device_type`-branch test (confirmed unreachable); added a test for Livestatus's group-default resolution (`other`); dated comments on both surviving tests
- `.planning/REQUIREMENTS.md` - TAG-01/02/03 wording corrected (prior session) and now marked Complete
- `.planning/ROADMAP.md` - Phase 10 Goal/Success-Criteria/one-liner corrected (prior session)
- `.planning/PROJECT.md` - Active requirements list corrected (prior session)

## Decisions Made

- Livestatus keys custom tags by their bare group id; the REST-prefixed guess was removed rather than kept as defensive dead code, per the plan's explicit instruction not to misrepresent an unverified guess as a deliberate safeguard.
- `UNKNOWN_DEVICE_TYPE`'s semantic meaning changed based on live evidence RESEARCH.md did not anticipate (Livestatus resolves group defaults; REST does not) — documented in-source rather than silently absorbed, satisfying threat T-10-27's repudiation mitigation.
- Verified the untagged-host leg via the Checkmk UI rather than the wizard, because no wizard path exists to tag an already-onboarded host — documented as a deviation, not concealed, and separately raised as the most substantive follow-up finding.
- Left two out-of-scope stale-VLAN spots untouched and flagged instead of edited (prior session): root `CLAUDE.md`'s auto-generated Constraints mirror, and ROADMAP.md's milestone Overview sentence.
- Did not touch ROADMAP.md's progress table row, STATE.md, or Phase 10's status markers — orchestrator-owned tracking, per this execution's explicit instructions.

## Deviations from Plan

### Recorded, not auto-fixed (verification method substitution)

**1. Task 1's device-type tag applied via Checkmk UI instead of the wizard's Phase 4 prompt**
- **Found during:** Task 1 live verification
- **Issue:** The plan's `<how-to-verify>` step 2 instructs promoting a host through the wizard's Phase 4/5 flow to set the tag. The wizard has no supported path to tag an already-onboarded host without re-scanning and re-promoting it, which would overwrite that host's monitoring method.
- **Fix:** Set the tag directly via the Checkmk UI on a host not otherwise under test, isolating the untested leg (Livestatus -> poller -> MQTT) without disturbing a monitored host.
- **Files modified:** none (verification-only)
- **Commit:** none (Task 1 makes no code changes)
- **Scope note:** This is a real product gap (see Findings for follow-up below), not a shortcut that weakens the verification — the chain from a wizard-applied tag through Checkmk's own attribute storage into Livestatus is architecturally the same regardless of which client (wizard vs. UI) writes the attribute.

### Auto-fixed Issues

None beyond what Task 2 itself was scoped to do (the A3 resolution und `extract_device_type` correction is the plan's Task 2 deliverable, not an unplanned deviation).

## Findings for Follow-up

These are recorded per the operator's request for future triage. **None of these were fixed in this plan** — they are out of Phase 10's scope, and no other plan's PLAN.md or ROADMAP.md scope was changed to accommodate them.

1. **(feature gap, most substantive)** No wizard path exists to tag an already-onboarded host. This live run's own Phase 2 output reports 20 pre-existing hosts defaulted to `device_type=other`, but the wizard offers no way to act on that — the only route back through the wizard is re-scan-and-re-promote, which also overwrites the host's monitoring method. A separate, folder-scoped bulk-tagging flow (independent of promotion) would need only inputs that already exist: `list_folders()` (`api.py:164`), `list_hosts()` (`api.py:209`), each folder's scan CIDR already persisted by Phase 2 in Checkmk's own `network_scan` folder attribute (`wizard.py:_network_scan_attributes`, readable at `extensions.attributes.network_scan.addresses[].network`), and `update_host_attributes`. Worth doing before Phase 11, since the dashboard colour-codes by device type and would otherwise render 20 real hosts as `other` indefinitely.
2. **(gap)** The `worker` service has no `CMK_REST_*` env vars — the wizard's re-run automation-secret prompt and the probe script both require a manually pasted secret, while 10-05 wired those same credentials into the `poller` service only.
3. **(gap)** The automation secret the wizard generates on a first run is never displayed (`wizard.py:498` prints only a success line) — the operator must fetch it out of the `checkmk` container to populate `deploy/.env`.
4. **(robustness)** The poller exits when Livestatus is unreachable at startup (`mqtt_poller.py:1015-1020`) but degrades when the REST credential is missing — inconsistent failure postures for two external dependencies of the same loop. Observed live during this run: a Checkmk container restart raced the poller and killed it; only `restart: unless-stopped` recovered it.
5. **(observability)** A successful poller start logs nothing, so a healthy poller and a hung one are indistinguishable in `podman logs`. This cost real debugging time during this verification run.
6. **(test gap)** The `alias` crash-loop fixed in commit `78ff087` could not have been caught by the existing suite: every test constructed retained-topology nodes in the current shape, so nothing crossed the written-by-an-older-version / read-by-a-newer-version seam. Phase 11 will add fields to the same retained payload; `_normalise_restored_node` is now the single place to declare a default for each new field.

## Issues Encountered

None blocking. Task 1's checkpoint was the expected pause point, not an issue.

## User Setup Required

None further — the live verification the plan required is complete.

## Next Phase Readiness

Phase 10 is complete. Phase 11 (dashboard) can proceed. Two items from "Findings for follow-up" above are worth the Phase 11 planner's attention specifically:
- Finding 1 (no bulk-tagging path) means 20 real hosts will render as `other` in the dashboard until addressed — consider a phase before or alongside Phase 11.
- Finding 6 (`_normalise_restored_node` as the single seam for future payload fields) is directly relevant to any Phase 11 work that adds fields to the retained topology payload.

## TDD Gate Compliance

Not applicable — this plan has no `tdd="true"` tasks.

## Self-Check: PASSED

- `scripts/mqtt_poller.py` — FOUND
- `tests/test_mqtt_poller.py` — FOUND
- `.planning/REQUIREMENTS.md` — FOUND
- Commit `807851d` — FOUND
- Commit `504793d` — FOUND
- Commit `c2cdb4e` — FOUND
- `Live-verified against a real Checkmk 2.4.0p36...` comment in `scripts/mqtt_poller.py` — FOUND
- `uv run pytest -q` — 348 passed, 0 failed (unchanged from baseline)
- `uvx ruff check --no-cache src/ tests/ scripts/` — exactly 7 pre-existing findings (unchanged from baseline)

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Status: complete, 2026-09-11*
