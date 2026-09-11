---
phase: 10-checkmk-tag-group-onboarding-integration
verified: 2026-09-11T09:26:52Z
status: human_needed
score: 4/4 roadmap criteria verified (1 with a noted, non-blocking deviation); TAG-01/02/03 satisfied
has_blocking_gaps: false
overrides_applied: 0
human_verification:
  - test: "Onboard a brand-new host through the live wizard's Phase 4 device-type prompt end to end (not via the Checkmk UI), and confirm the resulting Livestatus tags/MQTT payload match the UI-set case already observed"
    expected: "Same {'device_type': '<choice>'} Livestatus resolution and matching MQTT payload as the UI-tagged host verified in 10-06"
    why_human: "10-06's live run set the tag through the Checkmk UI, not the wizard's own Phase 4 prompt, because no wizard path exists to tag an already-onboarded host without re-promoting it. The Phase 5 attribute-application code path (`_device_type_and_alias_attributes`) is exercised only by mocked unit tests, never against a live site. The wizard-driven leg of the chain (Phase 4 prompt -> Phase 5 create_host -> real Checkmk attribute) is architecturally identical to the UI-driven leg but has not itself been observed live."
  - test: "Run the wizard against a fresh site with folders enabled, confirm device_type + alias + folder for a newly-onboarded (not pre-existing) host all appear correctly in one retained MQTT payload"
    expected: "New host's payload carries device_type from the operator's Phase 4 choice, alias from the Phase 4 prompt, and folder from the REST-derived path — sourced from the wizard's own onboarding, not a UI edit"
    why_human: "The 10-06 live run's two sampled hosts (192.168.0.1, test-machine) were pre-existing hosts on the site, tagged after the fact; no fully wizard-onboarded host with all three fields set through the wizard itself was captured in the retained payloads reviewed."
---

# Phase 10: Checkmk Tag-Group & Onboarding Integration Verification Report

**Phase Goal:** Checkmk captures device type per host and a location/group label is reliably
derived from folder structure, without silently mis-tagging existing hosts.
**Verified:** 2026-09-11T09:26:52Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths / Roadmap Success Criteria

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|---------|--------|----------|
| 1 | A new `device_type` host tag group exists with a config-driven, site-specific choice list, and every pre-existing host defaults to `other` (first) | VERIFIED | `device_types.json` (repo root) = `["other","E-link","ACS","Multimedia","NetworkDevice","GroupController"]`, `other` first (D-06). `_load_device_types()` fails loud if first entry != `"other"` (`src/checkmk_wizard/wizard.py:633`). `_ensure_device_type_tag_group()` (`wizard.py:693-756`) POSTs the group and counts pre-existing hosts lacking an explicit `tag_device_type` attribute. **Live-observed** (10-06, real 2.4.0p36.cre site, 20 pre-existing hosts): `device_type tag group created. 20 pre-existing host(s) defaulted to device_type='other'.` — matches the printed contract exactly. |
| 2 | Phase 4 prompts for device type per host, Phase 5 applies it, tag set via REST attribute shape `tag_<group_id>` verified live | PARTIALLY VERIFIED (see deviation) | Phase 4 prompt: `wizard.py:1036-1048` (`questionary.select` from `_load_device_types()`, optional alias text prompt). Phase 5 application: `_device_type_and_alias_attributes()` (`wizard.py:664-691`) derives `f"tag_{DEVICE_TYPE_TAG_GROUP_ID}"` (never a hardcoded literal — confirmed `grep -c '"tag_device_type"' wizard.py` → 0 outside the constant/comment), merged via `**`-unpack into all three `_onboard_hosts` attribute dicts (`wizard.py:1639,1661,1678`). REST attribute shape (`tag_device_type`) is live-verified only indirectly: the tag actually observed live in Livestatus/MQTT (`device_type: NetworkDevice`, `folder2`/core-router-1) was applied through the **Checkmk UI**, not through this wizard code path, because Phase 4's device-type prompt only fires for hosts being promoted from a fresh network scan — there is no wizard path to tag an already-onboarded host. The Phase 4->5 code path itself is exercised only by mocked unit tests (`tests/test_wizard.py`, 8 new tests per 10-04-SUMMARY), never against a live site. This is a genuine, honestly-disclosed gap in the phase's own verification, not a code defect — routed to human verification below rather than marked FAILED, since the code is substantively present, wired, and the same attribute-application mechanism (`create_host` with a `tag_<group>` key) is already proven live for `tag_agent`/`tag_snmp_ds` elsewhere in this codebase. |
| 3 | Location/group label derived from Checkmk folder association via REST structured folder segments (not raw string splitting), reflecting nested folder moves | VERIFIED | `derive_folder()` (the old raw Livestatus-`filename`-string-splitting function) is completely removed from `scripts/mqtt_poller.py` — `grep -n "def derive_folder"` returns nothing; only two explanatory comments referencing the old function's name/bug remain. `fetch_host_folders()` (`mqtt_poller.py:432-480`) is a standalone `urllib.request`-based REST GET against `domain-types/host_config/collections/all`, reading `extensions.folder` (a REST-computed structured field, immune to a site literally named `wato` — WR-07/Pitfall 10 closed) with no import of `checkmk_wizard` (preserving Phase 9's D-01 standalone-script constraint). **Live-observed** (10-06): retained payload `folder: "folder2"` sourced from REST's `/folder2`, with no `/omd`/`wato` segment. |
| 4 | Existing wizard Phase 4 classification tests still pass with the new tag prompt added | VERIFIED | `uv run pytest -q` → **357 passed, 0 failed** (current HEAD `24caea7`). The four pre-existing fixed-answer-iterator Phase 4 tests were repaired (not skipped) with the two new answers appended in prompt order (10-04-SUMMARY, `test_phase4_offers_ping_monitoring_method` etc.), and 8 new tests were added covering the device-type/alias behavior specifically. |

**Score:** 3/4 fully VERIFIED, 1/4 PARTIALLY VERIFIED (code substantively present and wired, live-verification leg incomplete for the wizard-specific application path) — routed to human_needed rather than gaps_found because the shortfall is a verification-coverage gap, not an implementation defect, and TAG-02's REST attribute *shape* itself is independently live-confirmed via the identical mechanism already used for `tag_agent`/`tag_snmp_ds`.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|---|---|---|---|
| TAG-01 | Device-type tag group, config-driven list, neutral `other` default | SATISFIED | Criterion 1 above; live-confirmed. |
| TAG-02 | Phase 4 prompts, Phase 5 applies, REST attribute shape verified live | SATISFIED, with the human-verification caveat above | Code fully present and wired; the specific "wizard-applied" leg of the live chain was not directly observed (UI was used instead) — noted honestly in 10-06-SUMMARY itself, not concealed. |
| TAG-03 | Folder-derived location/group label via REST structured segments | SATISFIED | Criterion 3 above; `derive_folder()` genuinely deleted, live-confirmed end to end. |

REQUIREMENTS.md marks all three `Complete` (lines 27-29, 83-85) — consistent with the evidence above, modulo the TAG-02 caveat.

### CONTEXT.md Decisions (D-01..D-10)

| Decision | Status | Evidence |
|---|---|---|
| D-01 (VLAN reframed as generic location/group label) | VERIFIED | `.planning/ROADMAP.md`/`REQUIREMENTS.md`/`PROJECT.md` wording reconciled (commit `c2cdb4e`, confirmed via `grep` above showing "location/group label" phrasing in ROADMAP SC3/REQUIREMENTS TAG-03). Poller field is named `folder`, not `vlan` (D-01's exact field name was Claude's Discretion; `folder` chosen and documented in 10-03-SUMMARY). |
| D-02 (no new tag group for location/group; folder label alone is sufficient) | VERIFIED | Only one new tag group (`device_type`) exists in `wizard.py`; no second tag group for folder/location was added anywhere in the diff. |
| D-03 (poller gains its own minimal REST client, no `checkmk_wizard` import) | VERIFIED | `fetch_host_folders`/`cmk_rest_base_url` use stdlib `urllib.request` only; `grep -n "import checkmk_wizard\|from checkmk_wizard" scripts/mqtt_poller.py` → no matches (confirmed by file inspection above; module docstring cites D-01 standalone constraint explicitly). |
| D-04 (replaces `derive_folder()`'s raw string-splitting; closes WR-07/Pitfall 10) | VERIFIED | `derive_folder()` deleted (see Criterion 3); WR-07 regression test `test_query_devices_wr07_site_named_wato_produces_correct_folder` exists per 10-03-SUMMARY. |
| D-05 (device-type list is a checked-in JSON config file) | VERIFIED | `device_types.json` at repo root. |
| D-06 (`other` first, neutral default) | VERIFIED | Confirmed in the file content and enforced by `_load_device_types()`'s fail-loud check; live-confirmed 20/20 pre-existing hosts defaulted correctly. |
| D-07 (Phase 4 prompt, `OnboardedHost.device_type`, applied as `tag_<group_id>` in Phase 5) | VERIFIED | Code present as described in Criterion 2; attribute key derived from `DEVICE_TYPE_TAG_GROUP_ID`, never a hardcoded string. |
| D-08 (post-creation backfill summary count) | VERIFIED | `_ensure_device_type_tag_group` prints the count; live-confirmed message text matches exactly (`"20 pre-existing host(s) defaulted to device_type='other'."`). |
| D-09 (optional alias prompt, native `alias` attribute, not a tag) | VERIFIED | `wizard.py:1043-1048` (blank -> `None`, non-blank stripped); applied as `attrs["alias"]` (no `tag_` prefix) only when set (`wizard.py:688-689`), so a wizard re-run never clears a UI-set alias. |
| D-10 (poller's Livestatus query gains `alias`, publishes it end-to-end) | VERIFIED | `alias` added to `OPTIONAL_HOST_COLUMNS`, `DeviceSnapshot.alias`, `publish_device_status` payload, `topology_nodes`, `topology_signature`, and `_normalise_restored_node` (backward-compat for older retained payloads). Live-confirmed distinct-from-hostname value (`core-router-1`). |

All 10 decisions are implemented in code, not merely claimed. D-03/D-04/D-06/D-10 (the load-bearing ones called out in the verification brief) all check out against current source, not SUMMARY prose.

### `derive_folder` Removal Check

`grep -n "def derive_folder" scripts/mqtt_poller.py` → **no output** (function does not exist). Only two dated comments reference the old name for historical context. `query_devices()` now takes a `folders: dict[str, str] | None` keyword parameter fed by `fetch_host_folders()`'s REST-sourced map. This is a genuine removal, not a dead/unused leftover.

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `_ensure_device_type_tag_group` backfill count | `defaulted` | `client.list_hosts()` REST response, counted by absence of `tag_device_type` | Yes — live-confirmed count of 20 against a real 20-host site | FLOWING |
| `fetch_host_folders` folder map | `folders` dict | REST `domain-types/host_config/collections/all`, `extensions.folder` | Yes — live-confirmed `'folder2'` from `/folder2` | FLOWING |
| `extract_device_type` | Livestatus `tags['device_type']` | Real Livestatus column | Yes — live-confirmed `NetworkDevice`/`other` | FLOWING |
| MQTT `alias` field | `DeviceSnapshot.alias` | Livestatus `alias` column | Yes — live-confirmed `core-router-1` distinct from hostname | FLOWING |

### Anti-Patterns Found

None of TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER found in the files this phase modified
(`src/checkmk_wizard/wizard.py`, `src/checkmk_wizard/api.py`, `scripts/mqtt_poller.py`,
`deploy/compose.yaml`). No debt-marker gate violations. `deploy/compose.yaml`'s
`CMK_REST_SECRET=${CMK_REST_SECRET:-}` is an intentional soft-degradation default (CR-01 fix),
not a stub.

### Behavioral Spot-Checks / Gate State

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full test suite | `uv run pytest -q` | 357 passed | PASS |
| Repo-wide lint | `uvx ruff check --no-cache src/ tests/ scripts/` | 7 findings, all confirmed pre-existing (present at phase baseline `58aa5f5`, all in `tests/test_wizard.py`, none touching this phase's added code) | PASS (no new findings) |
| `derive_folder` absent | `grep -n "def derive_folder" scripts/mqtt_poller.py` | no match | PASS |
| Tag literal not hardcoded | `grep -c '"tag_device_type"' src/checkmk_wizard/wizard.py` | 0 (only derived via `DEVICE_TYPE_TAG_GROUP_ID`) | PASS |
| compose.yaml poller REST env | `grep -n "CMK_REST" deploy/compose.yaml` | `CMK_REST_HOST`, `CMK_REST_PORT`, `CMK_SITE_ID`, `CMK_REST_USERNAME`, `CMK_REST_SECRET=${CMK_REST_SECRET:-}` all present | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh`-style shell probes exist in this repo's convention;
`scripts/probe_checkmk_rest_shapes.py` is a Python diagnostic run manually by the operator
against a live site, not an automated probe harness invoked by this verification. Its live run
(10-01) and findings are recorded as OBSERVED evidence per the task's pre-supplied context and
are cited above rather than re-run — re-running would require live Checkmk credentials not
available in this verification environment. **Skipped**: no automated probe target to execute
in-process.

### Human Verification Required

### 1. Wizard-driven device-type tagging, live

**Test:** Onboard a brand-new host through the actual wizard Phase 4 device-type prompt (not
via manual Checkmk UI edit), then check its Livestatus `tags` and the resulting MQTT payload.
**Expected:** Same shape as the UI-tagged host already observed live —
`{"device_type": "<chosen-value>"}` in Livestatus, matching value in the retained MQTT payload.
**Why human:** 10-06's own SUMMARY discloses that the live-verification run used the Checkmk UI
to set the tag, not the wizard, because Phase 4's device-type prompt only exists inside the
promote-from-scan loop — there's no wizard path to tag an already-onboarded host. The
Phase-4-to-Phase-5 code path (`_device_type_and_alias_attributes` -> `create_host`) has only ever
been exercised against mocked `respx` fixtures, never a live site. This is a code-path gap in
what was actually observed running, not something a static grep can settle.

### 2. Fully wizard-onboarded host end-to-end payload

**Test:** Run the wizard fresh against a site with folders enabled, onboard a genuinely new host
(not a pre-existing one) with a chosen device type and alias, and inspect its retained MQTT
`status`/`topology` payloads.
**Expected:** `device_type`, `alias`, and `folder` are all populated correctly and traceable to
the wizard's own prompts/REST calls, not a manual edit.
**Why human:** The two hosts sampled in 10-06's live run (`192.168.0.1`, `test-machine`) were
both pre-existing hosts, tagged/aliased after the fact via the UI or Phase 2's folder-move flow.
No single payload observed so far demonstrates the complete wizard-only path (scan -> Phase 4
prompts -> Phase 5 `create_host` -> Livestatus -> poller -> MQTT) for a newly onboarded host.

### Findings Carried Forward (Not Gaps — Explicitly Deferred by the Phase Itself)

The phase's own 10-06-SUMMARY records a substantive, self-identified product gap: **no wizard
path exists to retag an already-onboarded host** (bulk-tagging is deferred to a future phase or
before Phase 11). This does not block Phase 10's stated goal (new tag group exists, defaults are
safe, the wizard's onboarding-time flow supports device type/alias) but is worth carrying into
Phase 11 planning, since 20 real hosts on the live site will render as `other` indefinitely
without it. Also carried forward, all explicitly deferred and non-blocking per 10-REVIEW-FIX.md:
WR-03 (`folder=""` overload false-FAILs the smoke test's default/no-folders path), WR-04 (200-
but-empty REST response silently defeats the reuse guard), WR-07 (`_load_device_types()` re-read
per host in the Phase 4 loop, late-failing mid-run), WR-08 (backfill count can `AttributeError`
on a malformed/null `extensions`), WR-09 (undocumented assumption about `alias` defaulting to
hostname when unset). None of these were fabricated by this verification — all are pre-existing,
disclosed findings in `10-REVIEW.md`/`10-REVIEW-FIX.md`, reviewed here for severity and confirmed
non-blocking to the phase's 4 success criteria.

### Gaps Summary

No FAILED must-haves. The single partial item (Criterion 2 / TAG-02) is a live-verification
coverage gap, honestly disclosed by the phase's own SUMMARY, not a missing or stubbed
implementation — the code performing the wizard-side application is present, wired to the
correct attribute key, covered by unit tests, and uses the exact same REST mechanism already
proven live elsewhere in this codebase (`tag_agent`, `tag_snmp_ds`). Routing to
`human_needed` rather than `gaps_found` because closing it requires running the live wizard
against a real site, which this static verification pass cannot do, and because marking it
FAILED would misrepresent code that exists, is substantively implemented, and is wired
correctly, as absent.

---

_Verified: 2026-09-11T09:26:52Z_
_Verifier: Claude (gsd-verifier)_
