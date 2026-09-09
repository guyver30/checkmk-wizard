# Phase 10: Checkmk Tag-Group & Onboarding Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-09
**Phase:** 10-checkmk-tag-group-onboarding-integration
**Areas discussed:** VLAN-derivation fix scope, Device-type values & prompt placement, Existing-host backfill visibility, Alias usage (raised by user mid-discussion)

---

## VLAN-derivation fix scope (reframed to "location" mid-discussion)

The user pushed back on the initial framing — see "Reframe" note below — before answering the technical scope question.

### Reframe: what does folder-derived data actually mean?

**User's own words:** "I want to change this concept: the folder structure can be based because of VLANs splitting or something else (eg tower1, tower2, etc.). The group tagging is what really categorizes and organizes the different hosts, which is what we want to show in the dashboard UI. So in reality we have folders and group tagging, need to have a proper and simple way to manage and visualize them"

| Option | Description | Selected |
|--------|-------------|----------|
| Keep folder as a generic location label | Poller publishes folder path as-is under a generic field (`location`/`group`, not `vlan`) — no new tag group | ✓ |
| Replace folder-grouping with a second explicit tag | New "location" tag group, prompted during onboarding like device_type; folders no longer feed the dashboard | |

**User's choice:** Keep folder as a generic location label (recommended option).
**Notes:** Locked as D-01/D-02 in CONTEXT.md.

### Technical scope: where does the derivation fix live?

| Option | Description | Selected |
|--------|-------------|----------|
| Add a REST dependency to the poller | `scripts/mqtt_poller.py` calls Checkmk's REST folder-listing endpoint for structured segments, alongside its existing Livestatus TCP query | ✓ |
| Harden the existing string-parsing | Keep the poller REST-free; improve `derive_folder()`'s raw-string parsing (fixes WR-07's edge case) but stays string-based | |
| Leave it as-is / backlog | No changes to `scripts/mqtt_poller.py` this phase | |

**User's choice:** Add a REST dependency to the poller (recommended option).
**Notes:** Locked as D-03/D-04. The user needed the concept explained in detail first (why folders/VLAN were conflated, what "raw string splitting" vs "structured REST segments" concretely means) before answering — see full explanation given in the transcript.

---

## Device-type values & prompt placement

### Value list

| Option | Description | Selected |
|--------|-------------|----------|
| unknown, server, switch, router, ap, printer, nas, iot, other | Generic home/office categories | |
| Smaller set: unknown, server, network-device, iot, other | Coarser grouping | |
| **User's own answer (not a listed option):** "let's have a configuration file read by the wizard...by default we have: other, E-link, ACS, Multimedia, NetworkDevice, GroupController" | Configurable JSON list, site-specific defaults | ✓ (free text) |

**User's choice:** Configurable JSON config file, not a hardcoded list. Default values: `other, E-link, ACS, Multimedia, NetworkDevice, GroupController`.
**Notes:** Reveals an access-control/building-automation network context, not generic IT. Locked as D-05. Follow-up question confirmed JSON format (vs YAML) and confirmed "other" (not "unknown") is an acceptable safe first-listed default — see "Config file" sub-question below.

### Config file format/location

| Option | Description | Selected |
|--------|-------------|----------|
| JSON file in repo root or docs/, "other" as safe default | Simple ordered JSON list, operator-editable | ✓ |
| YAML file instead | Same idea, would need a new PyYAML dependency | |

**User's choice:** JSON file, "other" as safe default (recommended option).
**Notes:** Locked as D-05/D-06. Exact path left as Claude's Discretion.

### Prompt placement

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 4 — Classification | Grouped with existing per-host prompts (hostname, os_family, SNMP, ports) | ✓ |
| Phase 5 — Onboarding | Asked right before host creation/tagging | |

**User's choice:** Phase 4 — Classification (recommended option).
**Notes:** Locked as D-07.

---

## Existing-host backfill visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Print a summary count | Wizard queries and reports how many pre-existing hosts got defaulted | ✓ |
| Silent — no extra output | Trust Checkmk's documented auto-default behavior silently | |

**User's choice:** Print a summary count (recommended option).
**Notes:** Locked as D-08. Note the config-file decision above changed the default value from "unknown" to "other" — this question's wording (asked before the config-file answer) referenced "other" as already established.

---

## Alias usage (raised by user, not a pre-planned gray area)

**User's own words:** "every host has host name and an optional alias...is it better to use alias for dashboard or just rely on host name?"

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — optional alias prompt, alias-if-set else hostname | Phase 4 prompt, `create_host()` sets Checkmk's alias attribute, poller publishes it, dashboard prefers it | ✓ |
| No — hostname only | No changes | |

**User's choice:** Yes — optional alias prompt, alias-if-set else hostname (recommended option).
**Notes:** Locked as D-09/D-10. Poller-side publishing is in this phase's scope; dashboard's actual display preference is explicitly deferred to Phase 11.

---

## Claude's Discretion

- Exact device_type config file path/name (repo root vs new `config/` dir)
- Exact MQTT payload field name for the folder-derived label (`location` vs `group` vs `folder_label`)
- Exact REST client implementation shape for the poller's new folder-listing call
- Exact wording/formatting of the backfill summary count

## Deferred Ideas

- Simplifying `extract_device_type()`'s dual-key guessing (`device_type` vs `tag_device_type`) once the real tag's key shape is confirmed live — surfaced as a candidate area, not selected for discussion by the user.
- Dashboard rendering of alias/device_type/location (icons, colors, grouping UI) — Phase 11's scope.

---

*Phase: 10-checkmk-tag-group-onboarding-integration*
*Discussion logged: 2026-09-09*
