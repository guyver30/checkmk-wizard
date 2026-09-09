# Phase 10: Checkmk Tag-Group & Onboarding Integration - Context

**Gathered:** 2026-09-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Checkmk captures device type per host via a new host tag group, set through the wizard's onboarding flow, with pre-existing hosts safely defaulted rather than mis-tagged. A per-device location/group label (derived from Checkmk folder structure, reframed from the original "VLAN" assumption) and an optional display alias also flow from the wizard through to the poller's MQTT payload. This phase includes a scoped extension to Phase 9's `scripts/mqtt_poller.py` (a new REST dependency for structured folder reading, plus `alias` in the Livestatus query) — it does not include any dashboard rendering (Phase 11).

</domain>

<decisions>
## Implementation Decisions

### Terminology Reframe: "VLAN" → generic location/group label
- **D-01:** "VLAN" is reframed as a generic **location/group label**. A Checkmk folder represents whatever grouping the operator chose when running the wizard's Phase 2 (a VLAN, a physical location like `tower1`/`tower2`, a site, etc.) — it is never assumed to specifically mean VLAN. The poller publishes this as a generic field (e.g. `location` or `group`, not `vlan` — exact field name is Claude's Discretion), derived from the folder path and shown as-is.
- **D-02:** No new Checkmk tag group is added for location/group. The folder-derived label alone is sufficient for dashboard grouping. Only `device_type` gets its own explicit tag group in this phase.
- User's own framing (verbatim): "the folder structure can be based because of VLANs splitting or something else (eg tower1, tower2, etc.). The group tagging is what really categorizes and organizes the different hosts, which is what we want to show in the dashboard UI."
- **Follow-up needed:** `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` (TAG-03, PROJECT.md's Active list) still say "VLAN" — their wording should be reconciled to "location/group label" during planning or a follow-up doc pass, since it no longer matches this decision.

### Location/folder derivation touches Phase 9's poller
- **D-03:** `scripts/mqtt_poller.py` gains a **REST API dependency** (alongside its existing Livestatus-over-TCP query) specifically to fetch structured folder segments via Checkmk's REST API folder-listing endpoint — the same shape as `list_folders()` in `src/checkmk_wizard/api.py`. The poller **cannot import the `checkmk_wizard` package** (Phase 9's D-01 locks it as a standalone script) — it needs its own minimal REST client (e.g. a small `httpx` call), matching the file's existing "standalone, dependency-light" convention rather than pulling in the wizard's `CheckmkClient`.
- **D-04:** This replaces `derive_folder()`'s current raw Livestatus-`filename`-string splitting (`scripts/mqtt_poller.py:282-297`) with the REST-sourced structured path. Closes code-review finding WR-07 (breaks if the Checkmk site ID is itself named `"wato"`) and `.planning/research/PITFALLS.md` Pitfall 10 (folder-path-derived VLAN breaks silently on folder rename/restructure), since REST folder listing is immune to both.

### Device-type tag group
- **D-05:** The device-type choice list is **configurable via a checked-in JSON config file**, read by the wizard. Default/example list (from the user's own real-world context — an access-control/building-automation network, not generic home/office IT):
  ```json
  ["other", "E-link", "ACS", "Multimedia", "NetworkDevice", "GroupController"]
  ```
  Exact file path is Claude's Discretion (repo root, e.g. `device_types.json`, or a new `config/` directory) — this project has no prior precedent for a checked-in runtime config file, so pick something consistent with existing layout conventions (see `src/checkmk_wizard/wizard.py:40`'s `_SMARTMONTOOLS_DIR` pattern for how this repo resolves bundled non-Python assets relative to the checkout).
- **D-06:** `"other"` **must remain first** in the list. Checkmk auto-defaults every pre-existing host to whichever choice is listed first when a new tag group is created (research-confirmed: `.planning/research/PITFALLS.md` Pitfall 8) — there is no "unset" state and no explicit per-host backfill loop is needed. First-position is what matters, not the literal string "unknown" that ROADMAP.md/REQUIREMENTS.md currently use — `"other"` fills the same safe/neutral role.
- **D-07:** Wizard prompts for `device_type` in **Phase 4 (Classification)** (`src/checkmk_wizard/wizard.py:797`, `phase4_classification`), alongside the existing hostname/os_family/SNMP-version/expected-ports prompts — one interactive pass per host, matching the existing flow rhythm. `OnboardedHost` (`wizard.py:199`) gains a `device_type` field, threaded through to Phase 5's `create_host()` call (`api.py:193`) as the `tag_<group_id>` attribute (i.e. `tag_device_type`), following this project's already-proven tag-attribute-shape convention (`tag_agent`, `tag_snmp_ds`, `tag_criticality` — see `wizard.py:609,675,778,1454-1455`) and closing `.planning/research/PITFALLS.md` Pitfall 9 (wrong REST attribute shape for a new tag).
- **D-08:** After creating the device_type tag group, the wizard **prints a summary count** of how many pre-existing hosts were auto-defaulted (e.g. `"12 pre-existing hosts defaulted to device_type=other"`) — confirms the safe-default behavior actually happened rather than silently trusting it. Implementation: query `list_hosts()` after tag-group creation and count/report, no per-host detail needed.

### Alias
- **D-09:** Phase 4 also adds an **optional alias prompt** ("Display name/alias for {hostname} (blank to use hostname):"), alongside the device_type prompt. `OnboardedHost` gains an optional `alias` field, threaded to Phase 5's `create_host()` call as Checkmk's native `alias` host attribute when provided (not a custom tag — `alias` is a first-class Checkmk host attribute).
- **D-10:** `scripts/mqtt_poller.py`'s Livestatus query gains the `alias` column (added to `OPTIONAL_HOST_COLUMNS`, `scripts/mqtt_poller.py:69-77`); the per-device MQTT status/topology payload includes it. This phase's job is only to make the data available end-to-end (wizard sets it, poller publishes it) — the dashboard actually preferring alias-over-hostname for display is Phase 11's job, not this phase's.

### Claude's Discretion
- Exact device_type config file path/name
- Exact MQTT payload field name for the folder-derived label (`location` vs `group` vs `folder_label`)
- Whether `extract_device_type()`'s dual-key guessing (`device_type` vs `tag_device_type`, `scripts/mqtt_poller.py:300-307`) gets simplified once this phase confirms which key Livestatus actually returns for the real tag — not discussed with the user, a technical detail for research/planning to resolve once the tag group exists live
- Exact REST client implementation shape for the poller's new folder-listing call (minimal `httpx` usage matching this project's existing conventions)
- Exact wording/formatting of the pre-existing-hosts backfill summary count

</decisions>

<specifics>
## Specific Ideas

- User's own framing on folders vs tags: "the folder structure can be based because of VLANs splitting or something else (eg tower1, tower2, etc.). The group tagging is what really categorizes and organizes the different hosts, which is what we want to show in the dashboard UI. So in reality we have folders and group tagging, need to have a proper and simple way to manage and visualize them."
- Real-world device_type example list supplied by the user: `other, E-link, ACS, Multimedia, NetworkDevice, GroupController` — indicates an access-control/building-automation network deployment, not generic home/office IT. Researcher/planner should not assume generic "server/switch/router" categories are the only relevant case; the config-file approach exists precisely so this is site-specific and editable, not hardcoded.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tag-group & onboarding requirements
- `.planning/ROADMAP.md` — Phase 10 section (locked success criteria TAG-01/02/03; note SC1/SC3 use "VLAN"/"unknown" wording that D-01/D-06 above supersede — reconcile during planning)
- `.planning/REQUIREMENTS.md` — Tagging section (TAG-01, TAG-02, TAG-03 requirement text; same terminology-reconciliation note applies)
- `.planning/PROJECT.md` — Active requirements list (also uses "VLAN" wording predating this discussion's reframe)

### Research — pitfalls this phase must close
- `.planning/research/PITFALLS.md` — Pitfall 8 (silent default mis-tagging of pre-existing hosts — governs D-06/D-08), Pitfall 9 (wrong REST API attribute shape for a new tag — governs D-07), Pitfall 10 (folder-path-derived VLAN breaks silently on folder rename/restructure — governs D-03/D-04)
- `.planning/research/ARCHITECTURE.md` — poller component design, topic/payload contract (the location/alias fields this phase adds must fit the existing contract shape)
- `.planning/research/SUMMARY.md` — "Phase C: Tag-group/onboarding" section if present, plus Research Flags

### Phase 9 artifacts (poller code this phase extends)
- `scripts/mqtt_poller.py` — `derive_folder()` (line 282, to be replaced/hardened per D-03/D-04), `extract_device_type()` (line 300, dual-key guessing), `REQUIRED_HOST_COLUMNS`/`OPTIONAL_HOST_COLUMNS` (line 69-77, `alias` needs adding per D-10), the Live-verified citation block (line ~69-90) documenting what Phase 9 confirmed live (no host currently carries `device_type`/`tag_device_type` — this phase changes that)
- `.planning/phases/09-poller-core/09-VERIFICATION.md` and `09-04-SUMMARY.md` — Phase 9's live-verification findings relevant to extending the poller
- `.planning/phases/09-poller-core/09-REVIEW.md` — WR-07 finding (`derive_folder()`'s site-id-`"wato"` edge case), which D-04 closes

### Existing code patterns to follow
- `src/checkmk_wizard/api.py` — `list_folders()`/`create_folder()`/`update_folder_attributes()` (lines 150-189, folder REST pattern to mirror in the poller's new minimal REST client); `create_host()`/`update_host_attributes()` (lines 193-223, the `tag_<group_id>` attribute shape already proven for `tag_agent`/`tag_snmp_ds`/`tag_criticality`)
- `src/checkmk_wizard/wizard.py` — `phase4_classification()` (line 797, where the new device_type/alias prompts are added), `phase5_onboarding()`/`_onboard_hosts()` (line 1630/1386, where `create_host()` is actually called), `OnboardedHost` dataclass (line 199, gains `device_type`/`alias` fields), `phase2_folders()` (line 614, existing folder-level `tag_agent`/`tag_snmp_ds` default-attribute pattern — precedent for how Checkmk's tag-group-default auto-apply behavior is already relied on in this codebase)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `list_folders()`/`create_folder()`/`update_folder_attributes()` (`api.py:150-189`) — folder REST pattern; the poller's new minimal REST client (D-03) should read structured folder data the same way, without importing this module (poller stays package-independent).
- `create_host()`/`update_host_attributes()` (`api.py:193-223`) — already takes an `attributes: dict` with `tag_<group_id>` keys; adding `tag_device_type` and `alias` is a direct extension of an established call shape, no new API method needed on the wizard side.

### Established Patterns
- `phase4_classification()`'s per-host interactive prompt loop (`wizard.py:797-886`) — hostname → os_family → SNMP details → expected ports, appending each finished `OnboardedHost`. The new device_type/alias prompts slot into this same loop.
- `phase2_folders()`'s folder-level default-attribute pattern (`wizard.py:662-676`, setting `tag_agent`/`tag_snmp_ds` at folder creation) is the existing precedent for "Checkmk applies a default automatically" behavior this phase's tag-group creation also relies on (Pitfall 8).
- Project convention: `@dataclass` for structured records, `from __future__ import annotations`, dated live-verification citations for anything reverse-engineered from Checkmk's actual REST behavior (see `api.py:200-206`, `site.py:191-202` for the citation style to match when confirming the `tag_device_type` attribute shape and the folder-listing REST response shape live).

### Integration Points
- `OnboardedHost` → `create_host()`'s `attributes` dict (Phase 5) — where `device_type`/`alias` decisions become real Checkmk host attributes.
- `scripts/mqtt_poller.py`'s `query_devices()`/`DeviceSnapshot` (Phase 9) — needs both a new REST call (folder structure) and a new Livestatus column (`alias`) to carry this phase's data into the MQTT contract.

</code_context>

<deferred>
## Deferred Ideas

- Simplifying `extract_device_type()`'s dual-key guessing (`device_type` vs `tag_device_type`) once the real tag's key shape is confirmed live — surfaced as a candidate discussion area but not selected by the user; left for research/planning to resolve technically, not lost.
- Dashboard rendering of alias/device_type/location (icons, colors, grouping UI, alias-over-hostname display preference) — explicitly Phase 11's scope, not this phase's.

</deferred>

---

*Phase: 10-checkmk-tag-group-onboarding-integration*
*Context gathered: 2026-09-09*
