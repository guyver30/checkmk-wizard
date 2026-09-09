# Phase 10: Checkmk Tag-Group & Onboarding Integration - Research

**Researched:** 2026-09-09
**Domain:** Checkmk REST API (host tag groups, host attributes, folder structure) + wizard interactive-prompt extension + standalone-script REST client for the Phase 9 poller
**Confidence:** MEDIUM-HIGH (REST attribute-shape conventions are HIGH confidence, directly extending this codebase's own proven `tag_agent`/`tag_snmp_ds` pattern; the *new* REST surfaces this phase introduces — tag-group creation, folder-to-poller REST client, Livestatus `tags` key shape — are MEDIUM/LOW confidence, sourced from community forum posts and an official Ansible collection's source code rather than Checkmk's own docs, and explicitly flagged below for live verification against the real 2.4.0p35 CE site, consistent with this project's own "live-verify before shipping" convention)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Terminology Reframe: "VLAN" → generic location/group label**
- **D-01:** "VLAN" is reframed as a generic **location/group label**. A Checkmk folder represents whatever grouping the operator chose when running the wizard's Phase 2 (a VLAN, a physical location like `tower1`/`tower2`, a site, etc.) — it is never assumed to specifically mean VLAN. The poller publishes this as a generic field (e.g. `location` or `group`, not `vlan` — exact field name is Claude's Discretion), derived from the folder path and shown as-is.
- **D-02:** No new Checkmk tag group is added for location/group. The folder-derived label alone is sufficient for dashboard grouping. Only `device_type` gets its own explicit tag group in this phase.
- User's own framing (verbatim): "the folder structure can be based because of VLANs splitting or something else (eg tower1, tower2, etc.). The group tagging is what really categorizes and organizes the different hosts, which is what we want to show in the dashboard UI."
- **Follow-up needed:** `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` (TAG-03, PROJECT.md's Active list) still say "VLAN" — their wording should be reconciled to "location/group label" during planning or a follow-up doc pass, since it no longer matches this decision.

**Location/folder derivation touches Phase 9's poller**
- **D-03:** `scripts/mqtt_poller.py` gains a **REST API dependency** (alongside its existing Livestatus-over-TCP query) specifically to fetch structured folder segments via Checkmk's REST API folder-listing endpoint — the same shape as `list_folders()` in `src/checkmk_wizard/api.py`. The poller **cannot import the `checkmk_wizard` package** (Phase 9's D-01 locks it as a standalone script) — it needs its own minimal REST client (e.g. a small `httpx` call), matching the file's existing "standalone, dependency-light" convention rather than pulling in the wizard's `CheckmkClient`.
- **D-04:** This replaces `derive_folder()`'s current raw Livestatus-`filename`-string splitting (`scripts/mqtt_poller.py:282-297`) with the REST-sourced structured path. Closes code-review finding WR-07 (breaks if the Checkmk site ID is itself named `"wato"`) and `.planning/research/PITFALLS.md` Pitfall 10 (folder-path-derived VLAN breaks silently on folder rename/restructure), since REST folder listing is immune to both.

**Device-type tag group**
- **D-05:** The device-type choice list is **configurable via a checked-in JSON config file**, read by the wizard. Default/example list (from the user's own real-world context — an access-control/building-automation network, not generic home/office IT):
  ```json
  ["other", "E-link", "ACS", "Multimedia", "NetworkDevice", "GroupController"]
  ```
  Exact file path is Claude's Discretion (repo root, e.g. `device_types.json`, or a new `config/` directory) — this project has no prior precedent for a checked-in runtime config file, so pick something consistent with existing layout conventions (see `src/checkmk_wizard/wizard.py:40`'s `_SMARTMONTOOLS_DIR` pattern for how this repo resolves bundled non-Python assets relative to the checkout).
- **D-06:** `"other"` **must remain first** in the list. Checkmk auto-defaults every pre-existing host to whichever choice is listed first when a new tag group is created (research-confirmed: `.planning/research/PITFALLS.md` Pitfall 8) — there is no "unset" state and no explicit per-host backfill loop is needed. First-position is what matters, not the literal string "unknown" that ROADMAP.md/REQUIREMENTS.md currently use — `"other"` fills the same safe/neutral role.
- **D-07:** Wizard prompts for `device_type` in **Phase 4 (Classification)** (`src/checkmk_wizard/wizard.py:797`, `phase4_classification`), alongside the existing hostname/os_family/SNMP-version/expected-ports prompts — one interactive pass per host, matching the existing flow rhythm. `OnboardedHost` (`wizard.py:199`) gains a `device_type` field, threaded through to Phase 5's `create_host()` call (`api.py:193`) as the `tag_<group_id>` attribute (i.e. `tag_device_type`), following this project's already-proven tag-attribute-shape convention (`tag_agent`, `tag_snmp_ds`, `tag_criticality` — see `wizard.py:609,675,778,1454-1455`) and closing `.planning/research/PITFALLS.md` Pitfall 9 (wrong REST attribute shape for a new tag).
- **D-08:** After creating the device_type tag group, the wizard **prints a summary count** of how many pre-existing hosts were auto-defaulted (e.g. `"12 pre-existing hosts defaulted to device_type=other"`) — confirms the safe-default behavior actually happened rather than silently trusting it. Implementation: query `list_hosts()` after tag-group creation and count/report, no per-host detail needed.

**Alias**
- **D-09:** Phase 4 also adds an **optional alias prompt** ("Display name/alias for {hostname} (blank to use hostname):"), alongside the device_type prompt. `OnboardedHost` gains an optional `alias` field, threaded to Phase 5's `create_host()` call as Checkmk's native `alias` host attribute when provided (not a custom tag — `alias` is a first-class Checkmk host attribute).
- **D-10:** `scripts/mqtt_poller.py`'s Livestatus query gains the `alias` column (added to `OPTIONAL_HOST_COLUMNS`, `scripts/mqtt_poller.py:69-77`); the per-device MQTT status/topology payload includes it. This phase's job is only to make the data available end-to-end (wizard sets it, poller publishes it) — the dashboard actually preferring alias-over-hostname for display is Phase 11's job, not this phase's.

### Claude's Discretion
- Exact device_type config file path/name
- Exact MQTT payload field name for the folder-derived label (`location` vs `group` vs `folder_label`)
- Whether `extract_device_type()`'s dual-key guessing (`device_type` vs `tag_device_type`, `scripts/mqtt_poller.py:300-307`) gets simplified once this phase confirms which key Livestatus actually returns for the real tag — not discussed with the user, a technical detail for research/planning to resolve once the tag group exists live
- Exact REST client implementation shape for the poller's new folder-listing call (minimal `httpx` usage matching this project's existing conventions)
- Exact wording/formatting of the pre-existing-hosts backfill summary count

### Deferred Ideas (OUT OF SCOPE)
- Simplifying `extract_device_type()`'s dual-key guessing (`device_type` vs `tag_device_type`) once the real tag's key shape is confirmed live — surfaced as a candidate discussion area but not selected by the user; left for research/planning to resolve technically, not lost.
- Dashboard rendering of alias/device_type/location (icons, colors, grouping UI, alias-over-hostname display preference) — explicitly Phase 11's scope, not this phase's.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md, as written — see terminology note below) | Research Support |
|----|-------------|------------------|
| TAG-01 | A new Checkmk host tag group captures device type (server/switch/router/iot/etc.) with a neutral `unknown` default value, so pre-existing hosts aren't silently mis-tagged when the tag group is created | **Terminology reconciliation required** (see below): CONTEXT.md D-05/D-06 supersede this — the choice list is config-file-driven (`other, E-link, ACS, Multimedia, NetworkDevice, GroupController`, not generic `server/switch/router/iot`), and the neutral default is the string `"other"`, not `"unknown"`. Research confirms (MEDIUM confidence, Ansible-collection source + Checkmk docs quote) the REST payload shape for creating this tag group: `POST /domain-types/host_tag_group/collections/all` with `id`/`title`/`topic`(optional)/`tags: [{id, title, aux_tags}]` for Checkmk ≥2.4.0 (this project's verified baseline is 2.4.0p35) — see Code Examples. The "first tag = default, applied to ALL existing hosts automatically" behavior is doc-confirmed (docs.checkmk.com/latest/en/host_tags.html), matching Pitfall 8's fix. |
| TAG-02 | The wizard's Phase 5 onboarding flow prompts for and sets the device-type tag per host, using an attribute shape verified against a live Checkmk site's REST API | **Terminology reconciliation required**: CONTEXT.md D-07 locks the prompt into **Phase 4** (`phase4_classification`), not Phase 5 — Phase 5 (`_onboard_hosts`) only *applies* the already-collected `device_type`/`alias` via `create_host()`'s `attributes` dict, mirroring how `os_family`/`snmp_version` are also collected in Phase 4 and applied in Phase 5 today. `tag_device_type` is the correct REST attribute key (directly extends this codebase's own proven `tag_agent`/`tag_snmp_ds`/`tag_criticality` convention at `wizard.py:1454-1486`) — HIGH confidence, no new pattern needed. `alias` is a first-class Checkmk host attribute (not a tag), set as a plain `"alias": <value>` key in the same `attributes` dict. |
| TAG-03 | VLAN is derived from the host's Checkmk folder path via the REST API's structured folder segments, not raw string splitting | **Terminology reconciliation required**: per D-01/D-02, this is now a generic location/group label derived from the folder path, not specifically "VLAN," and lives in the *poller* (`scripts/mqtt_poller.py`'s `derive_folder()`), not the wizard. Research surfaces two viable REST field candidates for the "structured" source (see Architecture Patterns below) — both need live verification during Phase 10 execution. |

**Terminology reconciliation the planner must handle, not silently pick one:** `.planning/ROADMAP.md`'s Phase 10 section and `.planning/REQUIREMENTS.md`'s TAG-01/02/03 predate this CONTEXT.md discussion and use "VLAN"/"unknown"/"Phase 5" wording that D-01, D-06, and D-07 explicitly supersede. The plan's success-criteria language should use CONTEXT.md's terms (`other`, "location/group label", "Phase 4 prompts, Phase 5 applies") while still satisfying the underlying intent of TAG-01/02/03 — this is a wording gap in upstream docs, not a scope disagreement, and should be called out as a documentation follow-up (mirroring how Phase 9's own verification report flagged similar stale-bookkeeping gaps in ROADMAP.md/STATE.md/REQUIREMENTS.md).
</phase_requirements>

## Summary

This phase has three independent-but-related deliverables: (1) a new Checkmk `device_type` host tag group, config-file-driven, created idempotently by the wizard with `"other"` first so pre-existing hosts default safely; (2) two new Phase 4 prompts (`device_type` choice, optional `alias` text) whose answers flow into Phase 5's existing `create_host()`/`update_host_attributes()` calls as `tag_device_type` and `alias` respectively — a direct, low-risk extension of a pattern this codebase already uses three times over (`tag_agent`, `tag_snmp_ds`, `tag_criticality`); and (3) a standalone-script REST client added to Phase 9's `scripts/mqtt_poller.py`, replacing its Livestatus-`filename`-string-splitting `derive_folder()` with a REST-sourced folder path, plus an `alias` Livestatus column addition — closing WR-07 and PITFALLS.md Pitfall 10.

The wizard-side work (tag group creation + Phase 4/5 threading) is HIGH confidence: it's a straightforward extension of proven, already-live-verified conventions in `api.py`/`wizard.py`. The one genuinely new wizard-side REST call — `POST /domain-types/host_tag_group/collections/all` — has no existing precedent in this codebase and was not found in Checkmk's own official docs pages during this research pass; the field shape (`id`/`title`/`topic`/`tags: [{id, title, aux_tags}]` for Checkmk ≥2.4.0) is sourced from Checkmk's own `ansible-collection-checkmk.general` GitHub repository's `tag_group.py` module (an official Checkmk-org source, cross-checked against a forum post and the "Host tags" docs page's default-value wording) — MEDIUM confidence, must be live-verified against the real 2.4.0p35 site during Phase 10 execution, the same way this project already live-verifies every other REST payload shape before shipping it.

The poller-side REST client (D-03/D-04) is the least-certain part of this phase. Research surfaced two structurally different, non-mutually-exclusive candidate REST fields for "the host's folder, structured": (a) each host's own `extensions.folder` field on `GET /domain-types/host_config/collections/all` (a Checkmk-computed path string like `/tower1/rack2`, distinct from the raw OMD `filename` Livestatus already returns — no `wato`/site-id ambiguity since it never touches the filesystem layout at all), or (b) each host's `links` array entry with `rel: "urn:com.checkmk:rels/folder_config"`, whose `href` embeds the folder's own tilde-encoded id (e.g. `~network~wifi`, splittable on `~` into structured segments). Both close WR-07/Pitfall 10 equally well since neither depends on the literal string `"wato"` appearing in a filesystem path; (a) is simpler (one field, no folder_config cross-reference needed) and is the recommended default — but this is LOW-MEDIUM confidence (forum-post sourced, not Checkmk's own OpenAPI docs) and **must** be confirmed with a live `GET` against the real site before the planner locks in an implementation, per this project's own established practice.

A genuinely new, CONTEXT.md-unaddressed gap surfaced by this research: the poller currently has **no REST credentials at all** (Livestatus needs none; MQTT has its own `MQTT_USERNAME`/`MQTT_PASSWORD`). Adding a REST call means the poller needs a Bearer-token automation-user secret it has no existing way to obtain — this is a new configuration/provisioning surface the plan must explicitly account for (see Open Questions and Common Pitfalls below), not an oversight to paper over.

**Primary recommendation:** Extend `api.py` with one new method (`create_host_tag_group`, mirroring `create_folder`'s shape) and a `device_types.json` config loader in the wizard; thread `device_type`/`alias` through `OnboardedHost` → Phase 4 prompts → Phase 5's existing three `create_host()`/`_create_or_update_host()` call sites (snmp/ping/agent branches) exactly as `tag_agent`/`tag_snmp_ds` already are. For the poller, add a minimal stdlib-`urllib.request`-based (not `httpx`) REST helper reading a new `CMK_SITE_ID`/`CMK_REST_HOST`/`CMK_REST_PORT`/`CMK_REST_USERNAME`/`CMK_REST_SECRET` env-var group (reusing the `CMK_SITE_ID` name already established by the `checkmk`/`worker` services in `deploy/compose.yaml`), calling `host_config`'s per-host `extensions.folder` field once per poll cycle — live-verify the exact field shape against the real 2.4.0p35 site as the first task of this phase's execution, the same way Phase 9's 09-04 plan closed its own Livestatus-column assumptions.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `device_type` tag-group definition (choice list, `"other"` default) | API / Backend (Checkmk REST, called by wizard) | — | The tag group is Checkmk server-side config; the wizard is a one-shot CLI client that provisions it, not a runtime owner of it |
| `device_type` config choice list (JSON file) | Backend / Filesystem (wizard's own repo checkout) | — | Static, checked-in, read once per wizard run — no runtime service involved |
| Device-type/alias prompt collection | CLI / Terminal (wizard Phase 4) | — | Purely interactive, in-process `questionary` prompts, same tier as every other Phase 4 prompt |
| Device-type/alias persistence to Checkmk | API / Backend (Checkmk REST, `create_host`/`update_host_attributes`) | — | Same call already used for `tag_agent`/`tag_snmp_ds`; no new tier introduced |
| Folder → location/group label derivation | API / Backend (poller's new REST client, reading Checkmk's own computed folder path) | Database / Storage (Checkmk's WATO config, the ultimate source of truth for folder structure) | Must read Checkmk's *canonical* computed folder association, not re-derive it from a filesystem artifact (Livestatus `filename`) the poller has no business parsing |
| Location/group label + alias publication to MQTT | API / Backend (poller, publishing to the broker) | — | Same publish path (`publish_device_status`) as every other per-device field already in the payload; no new tier |
| Dashboard rendering of device_type/alias/location | Browser / Client (Phase 11, out of scope here) | — | Explicitly deferred; this phase only makes the data available end-to-end |

## Standard Stack

### Core

No new runtime packages are required for the wizard side — `httpx` (already `[project.dependencies]`, used throughout `api.py`) covers the new `create_host_tag_group()` call with no additional install.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | already pinned `>=0.28.1` (`pyproject.toml`) | Wizard-side `CheckmkClient.create_host_tag_group()` | Already the project's sole HTTP client; every other REST call in `api.py` uses it — no reason to diverge for this one new method |

### Supporting (poller-side REST client — new decision point)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `urllib.request` (stdlib) | n/a (stdlib) | Poller's new minimal REST call to Checkmk's `host_config` collection endpoint | **Recommended.** The poller's own module docstring (`scripts/mqtt_poller.py:1-35`) already establishes "standalone, dependency-light" as a deliberate design constraint — `paho-mqtt` is the *only* non-stdlib dependency it currently needs (MQTT genuinely has no usable stdlib client). A REST GET with one Bearer-token header and JSON-decode is a textbook stdlib case (`urllib.request.Request` + `json.loads`), and avoids adding a second `pip install` line to `deploy/compose.yaml`'s poller `command:` block (`scripts/mqtt_poller.py` currently needs exactly one: `paho-mqtt==2.1.0`). |
| `httpx` | `>=0.28.1` | Alternative for the poller's REST client, at the cost of a second pip-install line | Consider only if the plan values *implementation-style consistency* with `api.py`'s existing async httpx client over the "standalone, dependency-light" module-docstring constraint enough to accept the extra install step. Since the poller is single-threaded/synchronous (no `asyncio` anywhere in `scripts/mqtt_poller.py`), `httpx`'s sync client (`httpx.Client`, not `AsyncClient`) would be the fit, not the async one `api.py` uses — so consistency is partial either way. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `urllib.request` for the poller's REST client | `httpx.Client` (sync) | Nicer ergonomics (context manager, built-in JSON decode, better error types) at the cost of one more `pip install` line in `deploy/compose.yaml` and a divergence from the "minimal, standalone" framing already in the module's own docstring |
| Config-file-driven device-type list (JSON) | Hardcoded Python list/tuple constant in `wizard.py` | D-05 explicitly locks in the JSON-file approach — a hardcoded list would need a code change (and redeploy) for every operator's site-specific device-type taxonomy, defeating the stated purpose (the user's own example list is access-control/building-automation specific, not generic) |

**Installation:**
```bash
# No new packages needed if urllib.request (stdlib) is chosen for the poller.
# If httpx is chosen for the poller instead, add one line to deploy/compose.yaml's
# poller `command:` (mirroring the existing paho-mqtt install):
#   pip install --no-cache-dir paho-mqtt==2.1.0 httpx==0.28.1 && ...
```

**Version verification:**
```bash
$ uv run python -c "import httpx; print(httpx.__version__)"
```
`httpx` is already an installed, pinned project dependency (`pyproject.toml`) — no registry lookup needed; version is whatever `uv.lock` currently resolves (`>=0.28.1` constraint). No new package to verify against a registry for this phase if `urllib.request` is chosen.

## Package Legitimacy Audit

No new external packages are being introduced by this phase's recommended approach (stdlib `urllib.request` for the poller; `httpx` already a vetted, long-standing project dependency for the wizard side). The Package Legitimacy Gate protocol is therefore not applicable in its full form — documented here per the "Required whenever this phase installs external packages" trigger, which this phase does not meet under the recommended design.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `httpx` | PyPI | Pre-existing project dependency (already in `pyproject.toml`/`uv.lock`) | N/A — already vetted, in production use across `src/checkmk_wizard/api.py` | github.com/encode/httpx | Not run — no new install | Approved (pre-existing) |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new packages proposed)
**Packages flagged as suspicious [SUS]:** none

*If the planner instead chooses `httpx` for the poller's REST client (adding it to `deploy/compose.yaml`'s pip-install line), no new legitimacy concern is introduced — it is the same already-vetted `httpx` package, just installed into a second container.*

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Wizard (worker container, one-shot CLI run)                     │
│                                                                   │
│  device_types.json ──► phase4_classification()                  │
│  (checked-in config)      │  prompts: hostname, os_family, ...  │
│                            │  + device_type (NEW), alias (NEW)   │
│                            ▼                                     │
│                     OnboardedHost{device_type, alias, ...}       │
│                            │                                     │
│                            ▼                                     │
│              phase5_onboarding() / _onboard_hosts()              │
│                            │                                     │
│         create_host(attributes={..., "tag_device_type": ...,    │
│                                        "alias": ...})            │
│                            │                                     │
└────────────────────────────┼─────────────────────────────────────┘
                              ▼ REST POST/PUT (Bearer automation user)
                    ┌──────────────────────┐
                    │  checkmk container    │
                    │  (host_config,         │
                    │   host_tag_group)      │
                    └──────────┬─────────────┘
                              ▲ REST GET (NEW — needs its own
                              │  Bearer credential, see Open Questions)
                              │
┌─────────────────────────────┼─────────────────────────────────────┐
│ Poller (worker container, long-running daemon, Phase 9)          │
│                              │                                     │
│  every poll cycle:           │                                     │
│    Livestatus GET hosts ─────┴──► host state/tags/alias(NEW)      │
│    REST GET host_config ─────────► per-host folder path (NEW)     │
│                              │                                     │
│                    DeviceSnapshot{..., device_type, folder,       │
│                                   alias(NEW)}                     │
│                              │                                     │
│                              ▼                                     │
│              publish_device_status() → MQTT (unchanged shape,     │
│                                         new fields added)          │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
checkmk-wizard/
├── device_types.json           # NEW — D-05's config file, repo root
│                                # (mirrors _SMARTMONTOOLS_DIR's repo-root-
│                                # relative resolution pattern)
├── src/checkmk_wizard/
│   ├── api.py                  # + create_host_tag_group(), + get_host_tag_group()
│   │                            #   (idempotency check, mirrors get_folder's
│   │                            #   ETag-fetch pattern)
│   └── wizard.py                # phase4_classification() + 2 prompts,
│                                #   OnboardedHost + device_type/alias fields,
│                                #   _onboard_hosts()'s 3 create_host() call
│                                #   sites + tag_device_type/alias,
│                                #   NEW: tag-group-creation + backfill-count
│                                #   step (where in the flow is a planner
│                                #   decision — see Open Questions)
├── scripts/
│   └── mqtt_poller.py           # derive_folder() replaced with a REST call,
│                                #   OPTIONAL_HOST_COLUMNS + "alias",
│                                #   DeviceSnapshot + alias field,
│                                #   NEW: minimal REST helper + PollerConfig
│                                #   gains CMK_SITE_ID/CMK_REST_HOST/PORT/
│                                #   USERNAME/SECRET
└── tests/
    ├── test_api.py               # + create_host_tag_group tests (respx)
    ├── test_wizard.py            # existing phase4_* tests' answer-iterators
    │                              #   need 2 more entries each (device_type,
    │                              #   alias) — see Common Pitfalls
    └── test_mqtt_poller.py       # derive_folder tests replaced/extended;
                                   #   extract_device_type tests re-examined
                                   #   once the real Livestatus key shape is
                                   #   confirmed live
```

### Pattern 1: Tag-group creation via REST, `id`-based shape for Checkmk ≥2.4.0

**What:** `POST /domain-types/host_tag_group/collections/all` with a body of `{"id": <group_id>, "title": ..., "topic": ... (optional), "tags": [{"id": <tag_id>, "title": ..., "aux_tags": []}, ...]}`.
**When to use:** Once, idempotently, the first time the wizard needs the `device_type` tag group to exist — check first via `GET /objects/host_tag_group/device_type` (mirrors `get_folder()`'s existing ETag-fetch pattern in `api.py:173-178`); only POST if that returns 404.
**Source & confidence:** MEDIUM. Sourced from Checkmk's own `ansible-collection-checkmk.general` GitHub repository's `tag_group.py` module source (`Checkmk/ansible-collection-checkmk.general`, an official Checkmk-org repo, not a third party) — the module explicitly branches on Checkmk version: `"ident"` for `<2.4.0`, `"id"` for `>=2.4.0`. This project's own verified baseline is Checkmk CE 2.4.0p35, so `"id"` is the correct key. Cross-checked against a Checkmk forum thread confirming the same field names (`ident`/`id`, `title`, `topic`, `tags`) and the "Host tags" official docs page's wording on the default-value behavior. **Not yet verified against this project's own live site** — no existing code in this repo calls this endpoint. Live-verify as the first task of Phase 10 execution, per this project's established convention (every other REST payload shape in `api.py` carries a "Live-verified against a real Checkmk 2.4.0p35 CE site" citation; this one currently would not, until verified).

**Example:**
```python
# api.py — new method, mirrors create_folder()'s shape
async def create_host_tag_group(
    self, group_id: str, title: str, tags: list[dict[str, Any]], topic: str | None = None
) -> dict[str, Any]:
    """Create a new host tag group. Checkmk auto-defaults every existing
    host to `tags[0]`'s id — see PITFALLS.md Pitfall 8; callers must list
    the safe/neutral choice first.

    Field shape verified against Checkmk's own ansible-collection-
    checkmk.general `tag_group.py` module source (Checkmk 2.4.0+ uses
    "id", not "ident", for both the group and each tag entry) — NOT YET
    live-verified against this project's own site; do so before shipping.
    """
    body: dict[str, Any] = {"id": group_id, "title": title, "tags": tags}
    if topic:
        body["topic"] = topic
    resp = await self._request(
        "POST", "/domain-types/host_tag_group/collections/all", json_body=body
    )
    return resp.json()

async def get_host_tag_group(self, group_id: str) -> httpx.Response:
    """Idempotency check — mirrors get_folder()'s GET-then-inspect-status
    pattern. 404 means the tag group doesn't exist yet (safe to create);
    200 means it already does (skip creation, still safe to re-run the
    wizard)."""
    return await self._request(
        "GET", f"/objects/host_tag_group/{group_id}", expect=(200, 404)
    )
```

```python
# device_types.json — D-05's config file, "other" first (D-06)
["other", "E-link", "ACS", "Multimedia", "NetworkDevice", "GroupController"]
```

```python
# wizard.py — loading the config file, mirroring _SMARTMONTOOLS_DIR's
# repo-root-relative resolution (wizard.py:40)
_DEVICE_TYPES_PATH = Path(__file__).resolve().parents[2] / "device_types.json"

def _load_device_types() -> list[str]:
    choices = json.loads(_DEVICE_TYPES_PATH.read_text())
    if not choices or choices[0] != "other":
        # Defensive: D-06 is load-bearing (Pitfall 8) — fail loudly rather
        # than silently mis-tagging every pre-existing host.
        raise ValueError(f"{_DEVICE_TYPES_PATH} must list 'other' first")
    return choices
```

### Pattern 2: Extending `OnboardedHost` and the Phase 4→5 threading (proven pattern, direct extension)

**What:** Add `device_type: str` and `alias: str | None = None` fields to `OnboardedHost` (`wizard.py:198-211`); prompt for both at the end of `phase4_classification()`'s per-host loop (`wizard.py:797-885`), after the existing `expected_open_ports` prompt; thread both into all **three** `_onboard_hosts()` `create_host`/`_create_or_update_host` call sites (snmp: `wizard.py:1447-1458`; ping: `wizard.py:1469-1479`; agent-based linux/windows: `wizard.py:1481-1489`) via their `attributes` dict.
**When to use:** This is not a new pattern — it's the same one already used three times for `tag_agent`/`tag_snmp_ds`/`snmp_community`. No new abstraction needed.
**Source & confidence:** HIGH — directly reading the existing, already-live-verified code paths in this repo.

**Example:**
```python
# wizard.py — OnboardedHost gains two fields
@dataclass
class OnboardedHost:
    ip: str
    hostname: str
    folder: str
    os_family: str
    snmp_version: str | None = None
    snmp_community: str | None = None
    expected_open_ports: list[int] = field(default_factory=list)
    expected_services: list[str] = field(default_factory=list)
    device_type: str = "other"          # NEW (D-07) — defaults match the
                                          # tag group's own safe default
    alias: str | None = None             # NEW (D-09) — optional

# phase4_classification() — after the expected_open_ports prompt:
device_type = await questionary.select(
    f"Device type for {hostname}:",
    choices=[questionary.Choice(dt, value=dt) for dt in _load_device_types()],
).ask_async()

alias = (
    await questionary.text(
        f"Display name/alias for {hostname} (blank to use hostname):", default=""
    ).ask_async()
).strip() or None

# _onboard_hosts() — each of the 3 create_host() attribute dicts gains:
attributes = {
    ...,  # existing tag_agent/tag_snmp_ds/etc.
    "tag_device_type": h.device_type,
}
if h.alias:
    attributes["alias"] = h.alias
```

### Pattern 3: Poller-side folder derivation — two REST candidates, pick one, live-verify

**What:** Replace `derive_folder(filename: str)` (parses Livestatus's raw `filename` column, WR-07-vulnerable) with a function that derives the same information from a REST call the poller makes itself.

**Candidate A (recommended): `host_config`'s own `extensions.folder` field**
`GET /domain-types/host_config/collections/all` returns each host object with (per a Checkmk community forum example) an `extensions` block containing `"folder": "/some/path"` — a plain, Checkmk-computed path string, distinct from Livestatus's raw OMD `filename` (which encodes `/omd/sites/<SITE_ID>/etc/check_mk/conf.d/wato/<folder>/hosts.mk` and is what causes WR-07's `"wato"`-as-site-id collision). Splitting `"/some/path"` on `/` has no `wato`/site-id ambiguity at all, since this string is Checkmk's own semantic folder path, never a filesystem path. **One REST call per poll cycle covers every host** — no separate `folder_config` cross-reference needed.
**Confidence:** LOW-MEDIUM — sourced from a Checkmk community forum thread's example response, not Checkmk's own OpenAPI reference (which this research pass could not directly access — Checkmk's interactive Swagger docs are served from a running site's own `/ui/`, not a static page). **Live-verify this field's exact presence/shape as the first task of Phase 10's poller work.**

**Candidate B (fallback): folder-id extraction from the host's own `links` array**
The same `host_config` object's `links` array includes an entry with `rel: "urn:com.checkmk:rels/folder_config"` whose `href` embeds the folder's tilde-encoded id (e.g. `.../objects/folder_config/~network~wifi`). Stripping the leading `~` and splitting on `~` yields structured segments (`["network", "wifi"]`) — this is Checkmk's own canonical folder-id encoding (used throughout `api.py`'s existing `get_folder()`/`update_folder_attributes()` calls, e.g. `~vlan10`), so it is provably immune to WR-07 for the same reason Candidate A is. Slightly more parsing work (regex/URL-parse the href) than Candidate A.
**Confidence:** LOW-MEDIUM — same sourcing caveat as Candidate A.

**Recommendation:** Try Candidate A first during live verification (simpler); fall back to Candidate B only if `extensions.folder` turns out not to exist or not to carry the needed structure. Either way, this satisfies D-03/D-04's intent ("structured segments... immune to the site-id-named-'wato' edge case") — the CONTEXT.md phrasing ("same shape as `list_folders()`") pointed toward a `folder_config`-listing approach, but Candidate A's `host_config`-centric approach achieves the identical WR-07-closing property with one fewer REST call and no cross-referencing; flag this as a planning-time choice, not a silent deviation from CONTEXT.md's stated intent.

```python
# scripts/mqtt_poller.py — sketch, NOT yet live-verified
import urllib.request
import json as _json

def _rest_get_hosts_folders(base_url: str, auth_header: str, timeout: float) -> dict[str, str]:
    """Return {hostname: folder_path} via one REST call per poll cycle.

    Candidate A (see RESEARCH.md Pattern 3) — live-verify `extensions.folder`
    exists on this response shape against the real site before shipping.
    """
    req = urllib.request.Request(
        f"{base_url}/domain-types/host_config/collections/all",
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = _json.loads(resp.read())
    return {
        item["id"]: item.get("extensions", {}).get("folder", "")
        for item in data.get("value", [])
    }
```

### Anti-Patterns to Avoid

- **Re-deriving folder from Livestatus `filename` string-splitting, even with a smarter regex:** any fix that stays within "parse the OMD filesystem path string" (e.g. searching for the *last* `wato` segment instead of the first) still depends on an implementation detail (Checkmk's on-disk WATO layout) that has no schema guarantee — REST's `extensions.folder`/folder-id fields are Checkmk's own semantic representation, not a filesystem artifact, and are the correct fix per D-03/D-04's own stated intent, not just a WR-07 patch.
- **Creating the `device_type` tag group unconditionally on every wizard run:** must check existence first (`get_host_tag_group()` 404-vs-200) — a second `POST` for an already-existing tag group's `id` will error (or, per some Checkmk REST behaviors, silently no-op/replace tags in an undocumented way) and is untested territory; always gate on the idempotency check.
- **Hardcoding `"tag_device_type"` as a literal string in more than one place:** derive it from the config-loaded group id (`f"tag_{group_id}"`) if the group id itself ever needs to change, though D-05/D-07 fix the group id at `device_type` specifically — still worth a single named constant (e.g. `DEVICE_TYPE_TAG_GROUP_ID = "device_type"`) rather than repeating the literal across `api.py` calls, prompt code, and the poller's `extract_device_type()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting whether the `device_type` tag group already exists | A `list_hosts()`/`list_folders()`-style full scan checking for any host carrying the tag | `GET /objects/host_tag_group/device_type`, inspect the status code (404 vs 200) | One direct object lookup, not an N-host scan; mirrors `get_folder()`'s existing idempotency-check shape already in `api.py` |
| REST authentication for the poller's new HTTP call | A custom cookie-session flow (like `_gui_login()`) | Bearer-token automation-user auth (`Authorization: Bearer <user> <secret>`), the exact same scheme `CheckmkClient.__init__` already uses | The poller only needs read access to `host_config`; the GUI-session flow exists in `api.py` solely to bootstrap credentials *before* any automation user exists (Phase 1's chicken-and-egg problem), which does not apply here — an automation user already exists by the time the poller runs |
| Folder-path parsing | Any bespoke string-splitting on `/` or `~` performed against a Livestatus-sourced raw filesystem path | REST's own `extensions.folder` (a Checkmk-computed semantic string) or the folder-id embedded in a `links` href | Checkmk already computes and exposes the canonical folder association; parsing a filesystem-layout artifact ourselves is exactly the fragility class Pitfall 10/WR-07 already burned this project on once |

**Key insight:** Every piece of "parsing" this phase needs (tag defaults, folder association) is something Checkmk's own REST API already computes and exposes structurally — the fix in every case is "call the right REST endpoint," not "write a smarter parser."

## Common Pitfalls

### Pitfall 1: Tag group created with `"other"` NOT first, or created more than once with drifting tag lists (Pitfall 8 from PITFALLS.md, phase-specific instance)

**What goes wrong:** If `device_types.json` is ever edited to reorder entries (e.g. someone alphabetizes it, or adds a new type at the front), the tag group's *default* changes silently the next time the wizard creates it fresh — but since tag-group creation should be idempotent (only runs once, see Anti-Patterns), an edited `device_types.json` after the group already exists has **no effect at all** on the live Checkmk tag group unless the wizard also handles the "already exists, but the choice list changed" case (via `PUT`, not `POST`) — which D-05/D-06 do not explicitly ask for and is easy to silently skip.
**Why it happens:** The config file and the live Checkmk tag group can drift out of sync once created — the file is a *seed*, not a live mirror.
**How to avoid:** `_load_device_types()` should validate `choices[0] == "other"` and fail loudly (see Pattern 1's example) rather than silently accepting a misordered file; document explicitly (in-code comment, matching this project's dated-citation convention) that editing `device_types.json` after the tag group already exists on a site requires a manual `PUT` or does nothing.
**Warning signs:** Operator edits `device_types.json`, re-runs the wizard, sees no change in Checkmk's Setup > Tags GUI.

### Pitfall 2: The poller's new REST call has no credential-provisioning path (new gap, not covered by CONTEXT.md)

**What goes wrong:** `scripts/mqtt_poller.py`'s `PollerConfig` currently sources Livestatus (no auth) and MQTT (`MQTT_USERNAME`/`MQTT_PASSWORD`) credentials from env vars — there is no REST credential anywhere in the poller today. D-03 requires a REST call, which needs a Bearer-token automation-user secret, but no CONTEXT.md decision addresses *where that secret comes from* for the poller specifically.
**Why it happens:** The wizard already bootstraps an `automation` REST user in Phase 1 (`bootstrap_automation_user()`) and stores its secret on the `checkmk` container's own filesystem — but the poller runs in the `worker` container and (per this project's container-boundary constraint) must never touch `checkmk`'s filesystem, and per D-01/D-03 must not import `checkmk_wizard` either. There is currently no channel for that secret to reach the poller.
**How to avoid:** Add new poller env vars (`CMK_SITE_ID` — reuse this exact name, already established by `deploy/compose.yaml`'s `checkmk`/`worker` services with value `dmc`; `CMK_REST_HOST` defaulting to the same value as `LIVESTATUS_HOST`; `CMK_REST_PORT` defaulting to `5000`, matching the `check-mk-raw` image's internal REST/GUI port already documented in `api.py`'s `_site_base()`; `CMK_REST_USERNAME`/`CMK_REST_SECRET`), and document in the Podman setup doc that the operator must manually copy the wizard-bootstrapped `automation` user's secret into the poller's environment — mirroring how `MQTT_USERNAME`/`MQTT_PASSWORD` are already a manually-set, documented, rotatable default (`deploy/gen-mosquitto-passwd.sh`).
**Warning signs:** Poller's new REST call fails with 401/no-credential errors on every deployment until an operator manually wires this up; if unaddressed, folder derivation silently falls back to empty and the location/group label field goes blank for every device.

### Pitfall 3: Adding a REST call to the poller's per-cycle hot path introduces a second, differently-shaped failure mode

**What goes wrong:** `run_forever()`'s poll loop today has exactly one external-call failure mode (`LivestatusError`, caught and logged per-cycle, `scripts/mqtt_poller.py:852-864`). Adding a REST call without equally defensive handling (timeout, connection-refused, non-2xx, malformed JSON) risks either (a) an uncaught exception crashing the loop — the exact class of bug CR-01 already found and fixed for Livestatus row-parsing — or (b) a REST failure silently producing an empty/wrong folder for every device with no warning, if the failure path isn't logged.
**Why it happens:** It's tempting to bolt the new REST call directly into `query_devices()`'s existing per-row loop without giving it its own explicit try/except funneled through a single choke point, the way `_livestatus_request()` already does for Livestatus.
**How to avoid:** Wrap the new REST call in its own function with the same "normalize every failure into one custom exception type, catch it once per cycle, skip that cycle's *location* data (not the whole cycle) on failure" pattern already proven for Livestatus — degrade gracefully (log a warning, publish devices with `folder: ""` or the last-known value) rather than skipping the entire poll cycle over a REST hiccup.
**Warning signs:** No regression test exercises "REST call times out/returns 500/returns malformed JSON" — same gap class CR-01/CR-02 already found for this exact module in Phase 9's code review.

### Pitfall 4: Existing Phase 4 tests silently break (StopIteration) when the two new prompts are added

**What goes wrong:** Every existing `phase4_classification` test (`tests/test_wizard.py:820-1048`, e.g. `test_phase4_offers_ping_monitoring_method`) drives `questionary.Question.ask_async` via a fixed-length `answers = iter([...])` list matching today's exact prompt sequence. Adding two new prompts (device_type select, alias text) to the end of the per-host loop means every one of these tests' `answers` iterators is now one (or two) items short, and `next(answers)` will raise `StopIteration` — not a clean assertion failure, but an opaque test crash.
**Why it happens:** The test pattern hardcodes prompt *count and order*, not prompt *names* — any new prompt inserted into `phase4_classification()`'s loop, regardless of where, shifts every subsequent test's iterator.
**How to avoid:** Update every existing `phase4_classification`-driving test's `answers` list to append the two new answers (a device_type string matching one of `device_types.json`'s entries, and an alias string or `""`) in the same commit that adds the prompts — do not treat this as a separate "fix tests later" step. Directly addresses ROADMAP.md SC4's stated requirement ("Existing wizard Phase 5 onboarding tests still pass with the new tag prompt added" — noting again that the prompt itself lives in Phase 4 per D-07, only its *application* is Phase 5, so SC4's "Phase 5" wording needs the same reconciliation noted in Phase Requirements above).

### Pitfall 5: Livestatus's `tags` dict keys are very likely unprefixed — `extract_device_type()`'s `tag_device_type` guess is probably dead code (informs the Deferred simplification, does not resolve it)

**What goes wrong (informational, not a bug):** A Checkmk community-forum example of the Livestatus `hosts` table's `tags` column shows keys *without* the `tag_` prefix (`{"snmp_ds":"no-snmp","criticality":"prod","agent":"cmk-agent", ...}`) — every example key matches the tag group's bare `id`, not its REST-attribute name (`tag_<id>`). This strongly suggests (MEDIUM confidence, one community source, not this project's own live site) that once a real host carries `tag_device_type` via the REST API, Livestatus's `tags` column will expose it as `tags["device_type"]`, not `tags["tag_device_type"]` — meaning `extract_device_type()`'s second guess (`scripts/mqtt_poller.py:308-309`) is very likely unreachable dead code, not a defensive necessity.
**Why it happens:** REST's `tag_<id>` naming and Livestatus's bare-`<id>` naming are two independent, historically-separate conventions inside the same product — nothing forces them to match, and this codebase's own 09-04-SUMMARY.md already flagged this exact ambiguity as unresolved pending Phase 10.
**How to avoid:** Treat this as **confirmable, not assumed** — live-check `tags` on a real host carrying `tag_device_type` (create one via the new Phase 4/5 flow, then query Livestatus directly) as part of Phase 10 execution. If confirmed, the Deferred simplification (removing the `tag_device_type` guess) becomes safe to do in this phase rather than staying deferred — but this research does not make that call, since CONTEXT.md explicitly left it for "research/planning to resolve once the tag group exists live," and it does not yet exist live.
**Warning signs:** After Phase 10 ships, `extract_device_type()`'s `UNKNOWN_DEVICE_TYPE` fallback still fires for hosts that do have a `device_type` tag set — if so, the key-shape guess was wrong in the *other* direction and needs correcting, not just simplifying.

## Code Examples

Verified/derived patterns — see per-pattern confidence notes above; all REST payload shapes are MEDIUM confidence pending live verification.

### Idempotent tag-group creation, wired into the wizard flow
```python
# wizard.py — where this runs is a planning decision (Open Questions):
# candidates are early in phase2_folders() (folders exist before hosts do),
# or as a new small step at the top of phase4_classification() (closer to
# where device_type is actually used) — either satisfies D-08's "prints a
# summary count" requirement as long as it runs before any host is created
# with the tag applied to it.
async def _ensure_device_type_tag_group(client: CheckmkClient) -> None:
    resp = await client.get_host_tag_group("device_type")
    if resp.status_code == 200:
        return  # already exists — idempotent no-op, matches wizard's
                # "safe to re-run" convention elsewhere (phase2_folders,
                # _create_or_update_host)
    choices = _load_device_types()
    await client.create_host_tag_group(
        group_id="device_type",
        title="Device Type",
        tags=[{"id": c, "title": c, "aux_tags": []} for c in choices],
    )
    hosts = await client.list_hosts()
    defaulted = sum(
        1 for h in hosts
        if h.get("extensions", {}).get("attributes", {}).get("tag_device_type") == choices[0]
    )
    console.print(
        f"[green]device_type tag group created.[/green] "
        f"{defaulted} pre-existing host(s) defaulted to device_type={choices[0]!r}."
    )
```

### Poller REST helper — defensive wrapper matching the existing `LivestatusError` pattern
```python
# scripts/mqtt_poller.py — sketch
class RestError(RuntimeError):
    """Raised for any REST network failure or malformed response — same
    single-choke-point normalization pattern as LivestatusError."""

def _rest_get_hosts_folders(base_url, auth_header, timeout) -> dict[str, str]:
    try:
        req = urllib.request.Request(
            f"{base_url}/domain-types/host_config/collections/all",
            headers={"Authorization": auth_header, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise RestError(f"REST folder lookup failed: {exc}") from exc
    return {item["id"]: item.get("extensions", {}).get("folder", "") for item in data.get("value", [])}

# run_forever()'s cycle — degrade, don't crash, matching the LivestatusError precedent:
try:
    folders = _rest_get_hosts_folders(rest_base_url, rest_auth_header, timeout)
except RestError as exc:
    _logger.warning("Skipping folder refresh this cycle: %s", exc)
    folders = {}  # snapshots fall back to folder="" for this cycle only
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `derive_folder()` parses Livestatus's raw `filename` (OMD filesystem path), searching for the first `"wato"` segment | REST `host_config`/`folder_config` field, Checkmk-computed, no filesystem-path parsing at all | This phase (Phase 10) | Closes WR-07 (site-id-named-`"wato"` collision) and PITFALLS.md Pitfall 10 (folder rename/restructure fragility) at the root, not just patched |
| Every pre-existing host silently gets whatever tag is listed first when a new tag group is created (undocumented-by-default Checkmk behavior) | Same underlying Checkmk behavior, but *deliberately exploited*: `"other"` listed first on purpose (D-06), turning an implicit landmine into an explicit, documented safe default | This phase | Matches PITFALLS.md Pitfall 8's prescribed fix exactly |

**Deprecated/outdated:**
- Nothing in this phase deprecates existing wizard code paths — `tag_agent`/`tag_snmp_ds`/`snmp_community` attribute-setting patterns are extended, not replaced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `POST /domain-types/host_tag_group/collections/all` accepts `{"id": ..., "title": ..., "topic": ..., "tags": [{"id": ..., "title": ..., "aux_tags": [...]}]}` for Checkmk ≥2.4.0 (this project's 2.4.0p35 baseline) | Architecture Pattern 1, Phase Requirements TAG-01 | If wrong (e.g. `"ident"` still required, or `tags[].id` should be `tags[].ident`), tag-group creation fails with an opaque error (per PITFALLS.md Pitfall 9's own precedent — a 500 that doesn't obviously implicate the tag field) rather than working; low risk of *silent* wrongness since a malformed POST is very likely to error loudly, not succeed with wrong data |
| A2 | `GET /domain-types/host_config/collections/all`'s per-host `extensions` block includes a `folder` field containing a plain Checkmk-computed path string (e.g. `/tower1/rack2`) | Architecture Pattern 3 (Candidate A) | If this field doesn't exist or has a different shape, Candidate A fails and the plan must fall back to Candidate B (folder-id-from-links-href) — moderate risk, but non-blocking since Candidate B is a documented fallback, not a dead end |
| A3 | Livestatus's `hosts` table `tags` column exposes tag values keyed by the tag group's bare `id` (e.g. `"device_type"`), not the REST-attribute-prefixed `"tag_device_type"` | Common Pitfall 5 (informational only — no code change is proposed based on this assumption alone) | Low risk: `extract_device_type()` already defensively checks both keys, so being wrong here has zero functional impact — only affects whether the Deferred dual-key-guess simplification is safe to do in this phase |
| A4 | Checkmk's REST API requires a Bearer-token `automation`-type user (the same kind `bootstrap_automation_user()` already provisions) for read access to `host_config` — no anonymous/unauthenticated read path exists | Common Pitfall 2, Open Questions | If wrong (e.g. some read-only endpoints are unauthenticated), the credential-provisioning gap flagged in Pitfall 2 may be smaller than described — low risk to flag conservatively, since Checkmk's REST API is documented elsewhere in this codebase (api.py) as requiring Bearer auth for every other endpoint, with no exception noted |
| A5 | The `device_types.json` config file, once the `device_type` tag group already exists on a site, has no live effect if edited (creation is a one-time, idempotent operation) | Common Pitfall 1 | If the plan instead implements a "sync tag group on every run" (PUT-if-changed) rather than "create once," this assumption becomes moot — worth an explicit planning decision either way, not left implicit |

**If this table is empty:** N/A — see entries above; all REST-shape claims in this research need live confirmation before Phase 10 ships, consistent with this project's own established practice of citing "Live-verified against a real Checkmk 2.4.0p35 CE site" only after such confirmation actually happens (see `api.py:200-206`, `scripts/mqtt_poller.py:69-90`).

## Open Questions

1. **Where in the wizard's phase flow does tag-group creation (D-08's "prints a summary count") actually run?**
   - What we know: it must run before any Phase 5 `create_host()` call applies `tag_device_type`, and D-08 wants a count of *pre-existing* hosts that got auto-defaulted, which is most meaningful before any *new* hosts from the current run are created (otherwise the count conflates "genuinely pre-existing" with "just staged by this run's own Phase 3").
   - What's unclear: whether it belongs in `phase2_folders()` (parallel to that phase's existing `tag_agent`/`tag_snmp_ds` folder-default precedent), as a new tiny phase of its own, or at the top of `phase4_classification()` right before the device_type prompt choices are built (so the config file is loaded once, in the same place it's consumed).
   - Recommendation: run it once, early — before Phase 3's network scan stages any new placeholder hosts — so the "N pre-existing hosts" count is unambiguous. `phase2_folders()` (which already runs before Phase 3) or a small new step between Phase 1 and Phase 2 are both defensible; the planner should pick one and document why.

2. **How does the poller obtain its new REST credential in practice — a manual copy-paste step, or should the wizard itself write it somewhere the poller's env can pick up?**
   - What we know: the wizard already has the `automation` user's secret in memory during its own run (from `bootstrap_automation_user()` or read via `site.read_automation_secret()` in host-native mode); the poller runs in a separate container with no shared filesystem to `checkmk`, per this project's container-boundary constraint.
   - What's unclear: whether Phase 10's scope includes updating `deploy/compose.yaml`'s `poller` service definition and the Podman setup doc (documenting a manual env-var-copy step, matching the existing `MQTT_USERNAME`/`MQTT_PASSWORD` precedent) — or whether that's considered out of this phase's scope and left for a future phase/operational task.
   - Recommendation: in-scope — without it, D-03's REST call has no way to authenticate in the deployed stack, making the feature non-functional end-to-end despite being code-complete. Document as a manual, rotatable env var (same trust model as `MQTT_USERNAME`/`MQTT_PASSWORD`, `IN-02`'s already-accepted pattern).

3. **Should the poller's new REST call run every poll cycle (matching Livestatus's own per-cycle re-derivation), or be cached/refreshed less often?**
   - What we know: folder structure changes far less often than host status; Livestatus's own per-cycle full-requery is what makes the poller "self-healing... no persisted state" (PLR-02); ARCHITECTURE.md's Scaling Considerations table treats "a few hundred devices" as trivial at this project's LAN scale for a single additional per-cycle call.
   - What's unclear: whether adding a second full-fleet REST call every 60s (default `POLL_INTERVAL_SECONDS`) is worth the added latency/failure surface for data that rarely changes, versus refreshing it only when `topology_signature()` already detects a change (piggybacking on existing change-detection rather than adding a new cadence).
   - Recommendation: run it every cycle for the same self-healing reasoning already established for Livestatus (Pitfall 2's resolved pattern — always re-derive from source truth, never cache silently) — at this project's stated LAN scale (tens of devices), the added REST round-trip is not a meaningful cost, and caching reintroduces exactly the staleness-on-restart risk class Pitfall 2 was written to eliminate.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Live Checkmk 2.4.0p35 CE site (for REST payload-shape live verification) | Phase 10 execution — confirming Assumptions A1/A2/A3 | Not available in this research sandbox | — | None — this is a hard requirement for Phase 10's own execution (mirrors Phase 9's own `human_verification` checkpoint pattern in `09-VERIFICATION.md`); the plan must include an explicit live-verification checkpoint task, not assume the community-sourced shapes above are correct |
| `httpx` (wizard-side) | `create_host_tag_group()` | ✓ | already pinned `>=0.28.1` | — |
| `urllib.request` (poller-side, recommended) | Poller's new REST helper | ✓ (stdlib) | n/a | `httpx` (see Standard Stack alternatives) |

**Missing dependencies with no fallback:**
- Live Checkmk site access for REST-shape verification — this phase's plan must include a `checkpoint:human-verify` task (mirroring Phase 9's own pattern) before the tag-group-creation and poller-REST-client code can be considered done, not just written.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Partially — new poller REST credential | Bearer-token automation-user secret (existing Checkmk mechanism, not hand-rolled); stored as an env var, same trust model as existing `MQTT_USERNAME`/`MQTT_PASSWORD`/`CMK_PASSWORD` defaults already documented as "rotate before exposing beyond a trusted LAN" (IN-02) |
| V3 Session Management | No | No new session/cookie logic introduced — Bearer tokens are stateless, matching every existing `CheckmkClient` call |
| V4 Access Control | No new surface | The poller's new REST credential should be scoped read-only if Checkmk supports per-user role restriction tighter than `admin` (existing `bootstrap_automation_user()` already notes admin is used "for a single-operator setup tool" absent a narrower built-in role — same tradeoff applies to whichever user's secret the poller reuses) |
| V5 Input Validation | Yes | Device-type prompt: validated by construction (a `questionary.select` from a fixed, config-loaded choice list — no free-text device_type possible, unlike hostname/CIDR prompts elsewhere in this codebase that need regex validation). Alias prompt: free text, currently no validation proposed — Checkmk's own REST API will reject invalid `alias` values server-side (same pattern already relied on for `snmp_community`/hostname elsewhere), but the planner should confirm whether Checkmk imposes any length/character restriction on `alias` worth client-side pre-validation (not confirmed in this research pass — LOW confidence gap, flag for the plan's own live-verification step) |
| V6 Cryptography | No new crypto | No new crypto/hashing introduced; the new REST secret is an opaque server-issued token, handled the same way existing secrets (`MQTT_PASSWORD`, `CMK_PASSWORD`) already are in this codebase (env vars, never logged — `PollerConfig.__repr__` already has a precedent for this at `scripts/mqtt_poller.py:160-177` and must be extended to also redact the new `CMK_REST_SECRET` field) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| New REST secret logged in cleartext via a careless `print`/exception traceback in the poller's new REST helper | Information Disclosure | Extend `PollerConfig.__repr__`'s existing redaction pattern to the new `cmk_rest_secret` field (mirrors the already-documented T-09-02 constraint for `mqtt_password`); ensure the new `RestError` exception message never interpolates the raw `Authorization` header |
| Tag-group creation silently applied with the wrong default (`"other"` not actually first, per Pitfall 1) | Tampering (of monitoring data integrity, not a security boundary per se) | `_load_device_types()`'s fail-loud validation (Pattern 1's example) |

## Sources

### Primary (HIGH confidence)
- Existing repo source: `src/checkmk_wizard/api.py` (existing REST call shapes, `_request()` choke point, `create_folder`/`get_folder`/`create_host` patterns), `src/checkmk_wizard/wizard.py` (`OnboardedHost`, `phase4_classification`, `_onboard_hosts`, `phase2_folders`), `scripts/mqtt_poller.py` (`derive_folder`, `extract_device_type`, `PollerConfig`, `DeviceSnapshot`), `deploy/compose.yaml` (poller service env vars, existing `CMK_SITE_ID` usage elsewhere), `tests/test_wizard.py` and `tests/test_mqtt_poller.py` (existing test conventions) — all read directly in this research session

### Secondary (MEDIUM confidence)
- [tag_group.py — Checkmk/ansible-collection-checkmk.general (GitHub, official Checkmk-org repo)](https://raw.githubusercontent.com/Checkmk/ansible-collection-checkmk.general/main/plugins/modules/tag_group.py) — read directly via `curl`; confirms `POST /domain-types/host_tag_group/collections/all`, `id`/`title`/`topic`/`help`/`tags[].id`/`tags[].title`/`tags[].aux_tags` field shape, and the `id` (≥2.4.0) vs `ident` (<2.4.0) version split
- [Host tags — Checkmk official docs](https://docs.checkmk.com/latest/en/host_tags.html) — confirms "The first tag in the list is the default value! This means that all hosts that do not have an explicit setting for this tag group are automatically set to this value" (matches PITFALLS.md Pitfall 8's own citation of this same page)
- [\[BUG\] Create host using REST API with custom tags — Checkmk Community Forum](https://forum.checkmk.com/t/bug-create-host-using-rest-api-with-custom-tags/28261) — corroborates the `tag_<group_id>` REST attribute-key convention already used elsewhere in this codebase

### Tertiary (LOW confidence — flagged for live verification)
- Checkmk community forum threads on `folder_config`/`host_config` response shapes (`forum.checkmk.com/t/rest-api-show-all-folders...`, `forum.checkmk.com/t/rest-api-and-recursive-folders/43944`) — WebFetch-summarized forum content, not Checkmk's own OpenAPI reference; source of Architecture Pattern 3's two candidate REST fields, explicitly flagged throughout this document as needing live confirmation
- A Checkmk community wiki page's Livestatus `tags` column example (unprefixed key names) — source of Common Pitfall 5's informational finding about `extract_device_type()`'s likely-dead-code guess

## Metadata

**Confidence breakdown:**
- Standard stack (wizard side): HIGH — no new packages, direct extension of proven `httpx`/`api.py` patterns
- Standard stack (poller side): MEDIUM — `urllib.request` recommendation is sound stdlib engineering judgment, but the REST call it will make (Pattern 3) is not yet live-verified
- Architecture (tag-group creation): MEDIUM — field shape sourced from an official Checkmk-org GitHub repo (strong secondary source) but not this project's own live site
- Architecture (poller folder derivation): LOW-MEDIUM — two candidate approaches identified, neither confirmed against the real site; this is the single largest unresolved item in this research
- Pitfalls: HIGH for the wizard-side/testing pitfalls (directly observed from this repo's own code/tests); MEDIUM for the poller-REST-credential gap (a genuinely new architectural question, not sourced from an external claim needing verification, but from first-principles analysis of this project's own documented container-boundary constraint)

**Research date:** 2026-09-09
**Valid until:** 30 days for the wizard-side findings (stable, proven patterns); 7 days for the poller-REST-client findings specifically (LOW-MEDIUM confidence, must be re-verified live before the plan can be executed with confidence — treat as provisional until Phase 10's own execution confirms or corrects Assumptions A1-A3)

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Researched: 2026-09-09*
