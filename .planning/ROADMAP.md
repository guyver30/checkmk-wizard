# Roadmap: checkmk-wizard — MQTT Bridge & Live Dashboard Milestone

## Overview

The existing 7-phase wizard (Phase 1–7, already Validated and out of this milestone's scope) takes a bare Checkmk install to a fully onboarded, monitored network. This milestone bolts on a live view of that network: a resilient MQTT broker, a Livestatus-polling bridge that publishes per-device retained state, a small Checkmk tagging addition so devices carry a type and VLAN, and a static backend-less dashboard that renders it all in real time. The build order follows the project's chosen **Horizontal Layers** structure — broker infrastructure hardened first (persistence + ACLs from day one, not retrofitted), then the poller's topic contract and Livestatus-diff resilience, then the Checkmk tag-group/onboarding integration, and finally the dashboard, which is a pure consumer of the poller's contract and is therefore built last.

## Phases

**Phase Numbering:**

- Continues from the existing wizard's Phase 1–7 (Validated, out of scope for this milestone) — new work starts at Phase 8.
- Integer phases (8, 9, 10, 11, 12, 13): Planned milestone work.
- Decimal phases (8.1, 8.2): Urgent insertions (marked with INSERTED).

- [x] **Phase 8: Broker Infrastructure Hardening** - Mosquitto gains a durable, access-controlled WebSockets listener alongside its existing internal TCP listener
- [x] **Phase 9: Poller Core** - A resilient Livestatus-to-MQTT poller publishes the per-device topic contract and self-heals across restarts (completed 2026-09-09)
- [x] **Phase 10: Checkmk Tag-Group & Onboarding Integration** - A device-type host tag and a folder-derived location/group label are wired into the wizard's onboarding flow (completed 2026-09-11)
- [x] **Phase 10.1: Bulk Device-Type Tagging and Deployment Gaps** (INSERTED) - Urgent insertion after Phase 10 (completed 2026-09-12)
- [x] **Phase 11: Live Dashboard** - A static 3-page dashboard renders topology, device status, and history live from the poller's MQTT contract (completed 2026-09-16)
- [x] **Phase 11.1: Dashboard Layout and Light Palette** - The dashboard moves to KONE's light palette and a resizable three-pane layout (tree / map-or-details / event history), with a grouping combo and severity ordering (completed 2026-09-21)
- [ ] **Phase 12: Agent Metrics and Service Status** - The per-device drill-down gains live agent-derived metrics (CPU/RAM/disk/SMART) and per-service status from a new Livestatus services query
- [ ] **Phase 13: Wizard Parents Support and Topology Map** - The wizard populates Checkmk's `parents` attribute so the dashboard can render a real auto-derived topology map
- [ ] **Phase 14: Fleet Intelligence** - Service-impact framing, root-cause collapse, availability reporting on MinIO, a time-series store with Grafana, and failure prediction from SMART/disk/memory trends

## Phase Details

### Phase 8: Broker Infrastructure Hardening

**Goal**: The MQTT broker is durable and access-controlled, ready to serve both the poller and browser clients before either is built against it
**Depends on**: Nothing (first phase of this milestone; existing wizard Phase 1-7 already Validated)
**Requirements**: BRK-01, BRK-02, BRK-03
**Success Criteria** (what must be TRUE):

  1. A browser-based MQTT client (e.g. `mosquitto_sub -L ws://...` or `mqtt.js`) can connect over a WebSockets listener that is distinct from the existing internal TCP listener the poller uses to publish
  2. Restarting the mosquitto container preserves previously retained messages, because `persistence true` is set against a mounted volume
  3. The WebSocket listener enforces a read-only ACL — a WS client can subscribe to any topic but a publish attempt is rejected; only the poller's internal TCP connection can publish
  4. `compose.yaml` exposes the new WebSockets port to the LAN alongside the existing `1883` port

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Broker config artifacts: mosquitto.conf (two listeners, auth, persistence), mosquitto.acl (read-only wsreader), reproducible password-file generator
- [x] 08-02-PLAN.md — Canonical deploy/compose.yaml (corrected /mosquitto/config mounts, WS on host 9002) + paho-mqtt dependency

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-03-PLAN.md — Live smoke test proving BRK-01/02/03, Podman setup doc repointed at deploy/ (all four checks PASSED on real deployment host)

### Phase 9: Poller Core

**Goal**: A long-running poller keeps MQTT retained state in sync with Checkmk Livestatus, self-healing across restarts with no persisted state of its own required
**Depends on**: Phase 8
**Requirements**: PLR-01, PLR-02, PLR-03, PLR-04, PLR-05, PLR-06, PLR-07, PLR-08
**Success Criteria** (what must be TRUE):

  1. `mosquitto_sub` on `lan/devices/+/status` shows retained per-device status with full OK/WARN/CRIT/UNKNOWN/DOWN granularity, a timestamp, and downtime/acknowledgement flags, republished every poll cycle
  2. Restarting the poller process does not cause an incorrect republish storm — status matches Livestatus's live current state each cycle, not the poller's own in-memory history
  3. `lan/devices/topology` republishes only when a host is added, removed, or reparented; unrelated poll cycles produce no new topology publish
  4. Deleting a host from Checkmk produces empty tombstone payloads on its `lan/devices/{id}/status` and `lan/devices/{id}/history` topics within one poll cycle, and it disappears from `lan/devices/topology`; bounded `lan/devices/{id}/history` and `lan/events/recent` feeds append only on actual state transitions
  5. `lan/poller/status` carries a birth message on poller startup and moves to an offline/LWT state when the poller process dies ungracefully

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 09-01-PLAN.md — Poller foundation: env-var config, topic-injection guard, worst-of state aggregation, bounded-log/topology helpers, and the single-round-trip Livestatus JSON query layer with a live column probe

**Wave 2** *(blocked on Wave 1)*

- [x] 09-02-PLAN.md — MQTT layer: birth/LWT client lifecycle, the five publish helpers at their resolved QoS/retain, broker-retained startup reconciliation, and the poll cycle (transitions, tombstones, topology diff, heartbeat)

**Wave 3** *(blocked on Wave 2)*

- [x] 09-03-PLAN.md — Dedicated `poller` compose service, `scripts/smoke_test_poller.py` live verification script, and Podman setup doc coverage of the service, topic contract and smoke test

**Wave 4** *(blocked on Wave 3)*

- [x] 09-04-PLAN.md — Live verification on the deployment host (blocking checkpoint), then record the confirmed Livestatus column set in-source and apply any corrections

### Phase 10: Checkmk Tag-Group & Onboarding Integration

**Goal**: Checkmk captures device type per host and a location/group label is reliably derived from folder structure, without silently mis-tagging existing hosts
**Depends on**: Nothing beyond the existing wizard (technically independent of Phase 9's poller; sequenced third per this milestone's chosen horizontal-layer build order so real device-type/location data exists before dashboard integration testing)
**Requirements**: TAG-01, TAG-02, TAG-03
**Success Criteria** (what must be TRUE):

  1. A new `device_type` host tag group exists in Checkmk with a config-driven, site-specific choice list, and every pre-existing host is defaulted to the neutral `other` value (listed first in the group) rather than a real device type
  2. The wizard's Phase 4 classification flow prompts for device type per host, Phase 5 onboarding applies it, and the tag is set via a REST API attribute shape (`tag_<group_id>`) verified against a live Checkmk 2.4.0p36 site
  3. A host's location/group label is derived from its Checkmk folder association via the REST API's structured folder segments (not raw string splitting), correctly reflecting nested folder moves
  4. Existing wizard Phase 4 classification tests still pass with the new tag prompt added

**Plans**: 6 plans
Plans:
**Wave 1**

- [x] 10-01-PLAN.md — device_types.json config list + stdlib REST/Livestatus shape probe script, run live to resolve the tag-group POST body, the per-host folder field, and the Livestatus tags key shape

**Wave 2** *(blocked on Wave 1)*

- [x] 10-02-PLAN.md — CheckmkClient.create_host_tag_group/get_host_tag_group, the validated device_types loader, and the idempotent tag-group provisioning step with its pre-existing-host default count
- [x] 10-03-PLAN.md — Poller: alias column end-to-end, RestError + REST folder lookup replacing derive_folder's filename parsing, PollerConfig REST credentials with the secret redacted

**Wave 3** *(blocked on Wave 2)*

- [x] 10-04-PLAN.md — Phase 4 device_type/alias prompts, Phase 5 tag_device_type/alias on all three host-creation call sites, and repair of every answer-iterator-driven test
- [x] 10-05-PLAN.md — Poller deployment wiring: compose CMK_REST_* env block, a smoke-test enrichment check, and setup-doc credential provisioning plus the updated topic contract

**Wave 4** *(blocked on Wave 3)*

- [x] 10-06-PLAN.md — Live end-to-end verification (blocking checkpoint), extract_device_type corrected to the confirmed Livestatus key shape, and ROADMAP/REQUIREMENTS/PROJECT terminology reconciliation

### Phase 10.1: Bulk Device-Type Tagging and Deployment Gaps (INSERTED)

**Goal**: An operator can correct device type and alias on already-onboarded hosts without re-promoting them, and the poller/worker deployment stops requiring hand-copied credentials or silent-failure guesswork
**Depends on**: Phase 10
**Requirements**: TAG-04, OPS-01, OPS-02, OPS-03, OPS-04
**Source**: Phase 10 self-identified follow-up findings 1-5 (`.planning/phases/10-checkmk-tag-group-onboarding-integration/10-06-SUMMARY.md`, "Findings for Follow-up"), carried forward by `10-VERIFICATION.md`
**Success Criteria** (what must be TRUE):

  1. A folder-scoped bulk retag flow exists that lists already-onboarded hosts and updates `tag_device_type` and `alias` via `update_host_attributes`, without running promotion or altering the host's monitoring method
  2. The `worker` compose service carries the same `CMK_REST_*` environment block the `poller` service already has, so the wizard re-run and the probe script no longer need a hand-pasted secret
  3. The automation secret the wizard generates on a first run is displayed to the operator at the point it is created, sufficient to populate `deploy/.env` without shelling into the `checkmk` container
  4. The poller survives a transient Livestatus outage at startup (the observed container-restart race) via a bounded retry, instead of exiting immediately; the deliberate asymmetry with the REST credential's always-degrade posture is preserved and recorded in-source, since Livestatus is the sole mandatory data source (Phase 10 decision D-03)
  5. A successful poller start emits a log line identifying the configured site, poll interval, and broker, so a healthy poller is distinguishable from a hung one in `podman logs`

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 10.1-01-PLAN.md — Live-verify whether a partial host-attribute PUT merges or replaces (blocking probe + checkpoint)
- [x] 10.1-02-PLAN.md — Deployment/observability gaps: worker CMK_REST_* env, automation secret display, poller startup retry and success log

**Wave 2** *(blocked on Wave 1)*

- [x] 10.1-03-PLAN.md — Detection-driven folder-scoped bulk retag inside Phase 4, with activation and Phase 4 answer-iterator audit

### Phase 11: Live Dashboard

**Goal**: A static, backend-less dashboard renders live Checkmk-derived topology, device status, and history purely by consuming the poller's MQTT contract
**Depends on**: Phase 8, Phase 9, Phase 10
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06
**Success Criteria** (what must be TRUE):

  1. `index.html` renders an at-a-glance stats-by-state strip above a grouped fleet overview, with hosts icon-coded by device type and grouped/colored by either the folder-derived location/group label or the device type (runtime toggle); incoming updates merge in place without a full re-render
  2. `devices.html` shows a live sortable device table and a recent-events panel that update in place as MQTT messages arrive
  3. `details.html` shows a per-device drill-down with a bounded status-history strip and a link out to Checkmk's own UI for that host
  4. A device whose last-seen timestamp exceeds a staleness threshold, or whose poller liveness signal (`lan/poller/status`) is stale, is shown in a distinct stale/unknown visual state separate from "down"
  5. The dashboard shows a connection-status indicator and reconnects with jittered exponential backoff when the MQTT-over-WebSockets connection drops

**Plans**: 9 plans in 5 waves

Plans:
**Wave 1**

- [x] 11-01-PLAN.md — D-17 poller extension: additive `staleness` + `host_state_raw`, tests, live column probe (wave 1)
- [x] 11-02-PLAN.md — Vendor mqtt.js 5.15.2 + KONE fonts/icons/logo, write `config.js`, add the `dashboard` nginx service on 8090 (wave 1)
- [x] 11-03-PLAN.md — KONE-branded stylesheet plus the three shared-shell HTML pages (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [x] 11-04-PLAN.md — Pure helpers: staleness derivation, display/classification, worst-of roll-up (wave 2)
- [x] 11-05-PLAN.md — Wholesale-replace state store and the MQTT-over-WS connection with hand-rolled jittered backoff (wave 2)

**Wave 3** *(blocked on Wave 2)*

- [x] 11-06-PLAN.md — Persistent shell (indicator, banners, grouped tree, event panel) and the pushState router with its ViewModule contract (wave 3)

**Wave 4** *(blocked on Wave 3)*

- [x] 11-07-PLAN.md — index stats strip + grouped fleet overview, and the sortable device table (wave 4)
- [x] 11-08-PLAN.md — Per-device detail panel, bounded history strip, Checkmk deep link (wave 4)

**Wave 5** *(blocked on Wave 4)*

- [x] 11-09-PLAN.md — Deployment/README documentation plus live verification of all five success criteria (wave 5)

**UI hint**: yes

### Phase 12: Agent Metrics and Service Status

**Goal**: The dashboard's per-device drill-down shows live agent-derived metrics and per-service status, sourced from a new Livestatus `services` query published on its own MQTT topic
**Depends on**: Phase 11
**Requirements**: PLR-09, PLR-10, PLR-11, PLR-12, DASH-08, DASH-09, DASH-10, DASH-11, DASH-03 (partial)
**Requirements note**: PLR-09..PLR-12 and DASH-08..DASH-11 were minted in REQUIREMENTS.md during this phase's planning pass (2026-09-21), per 12-RESEARCH.md's recommendation — Phase 12's scope existed only as ROADMAP prose until then. DASH-03 is only PARTIALLY covered: this phase ships its bounded per-device status-history strip (D-16) but deliberately not its "link out to Checkmk's own UI" clause (D-17), so DASH-03 must stay `Partial`, not `Complete`, after this phase verifies.
**Scope** (from `.planning/phases/11-live-dashboard/11-CONTEXT.md` deferred section):

  1. Extend `scripts/mqtt_poller.py` with a `GET services` Livestatus query — it currently issues only `GET hosts`, so per-service state, `plugin_output` and `perf_data` do not exist anywhere in the contract today
  2. Parse Nagios-format `perf_data` in the poller (Python), not in browser JS, and publish structured values on a new retained per-device services topic
  3. Render CPU / RAM / disk-space gauges and disk-health (SMART) readouts on the detail panel — `docs/DMC-server.png` is the visual reference
  4. Render a per-host service status list that explains *why* a host is red
  5. Settle the publish cadence: ~21 hosts × ~20 services is ~420 rows per cycle, so change-only publishing is likely required rather than every-cycle retention
  6. Amend PROJECT.md's "Duplicating Checkmk's own per-service drill-down UI" Out of Scope entry, which this phase partially reverses

**Note**: host color is *already* influenced by service state — the poller folds `worst_service_state` in via worst-of aggregation (Phase 9 D-08). This phase adds visibility into which service is failing, not the influence itself.

**Plans**: 5 plans
Plans:
**Wave 1**

- [ ] 12-01-PLAN.md — Poller services foundation: `GET services` column triad, Nagios `perf_data` parser, `ServiceSnapshot`/`query_services`, plus a `--dump-service-names` diagnostic for confirming Checkmk's SMART service naming live
- [ ] 12-03-PLAN.md — Dashboard data layer: gauge fields + `ServiceEntry`/`ServiceHistoryEntry` types, two new subscribed topics and store slices, and the `gaugeColor`/`smartBadge`/`compareServices` helpers
- [ ] 12-05-PLAN.md — Tree-row navigation into `/details?id=` (D-15) and the PROJECT.md Out of Scope amendment (scope item 6)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 12-02-PLAN.md — Poller publishing: gauge/SMART/service-list classification, `lan/devices/{id}/services` (change-only) and `lan/devices/{id}/service_history` (bounded), extended status payload and tombstones, cycle wiring
- [ ] 12-04-PLAN.md — `DetailsRoute` fill-in: CPU/RAM/Disk gauge row, other-mounts and SMART badges, per-service `Table` sorted worst-first, per-device history strip (DASH-03's history half)

### Phase 13: Wizard Parents Support and Topology Map

**Goal**: Checkmk's `parents` host attribute is populated by the wizard, so the dashboard can render a real, auto-derived topology map instead of a hand-maintained diagram
**Depends on**: Phase 11 (the dashboard shell the map drops into — independent of Phase 12)
**Requirements**: DASH-07
**Requirements note**: DASH-07 is the vis-network topology-map half split out of DASH-01 on 2026-09-12. Additional requirement IDs covering the wizard's `parents` support still need defining in REQUIREMENTS.md before this phase is planned.
**Scope** (from `.planning/phases/11-live-dashboard/11-CONTEXT.md` deferred section):

  1. Teach the wizard to set Checkmk's `parents` host attribute over the REST API, the same way Phase 10 sets `tag_device_type`. This makes topology real monitoring data, benefits Checkmk's own views, and removes the need for any dashboard-side layout persistence
  2. Build the vis-network topology map into `index.html`, replacing the Phase 11 grouped-overview panel (D-24 reserves that slot for exactly this)
  3. Vendor `vis-network` 10.1.2 standalone UMD into `dashboard/js/vendor/` — Phase 11 vendors only mqtt.js
  4. Apply Phase 11's already-reasoned map decisions rather than re-deriving them: **D-08** (parentless hosts attach to a synthetic, distinctly-styled group-root node) and **D-09** (physics stabilizes once on load then freezes, so `DataSet.update()` recolors in place without disturbing pan/zoom). Both are fully argued in `11-DISCUSSION-LOG.md`
  5. The map inherits Phase 11's grouping toggle (D-05), worst-of roll-up with count badge (D-06), Checkmk palette (D-11), and staleness treatment (D-12/D-15) — these were deliberately kept in Phase 11 so they drive the tree and overview too

**Open question for this phase's discussion**: if a hand-drawn map is still wanted after `parents` support lands, layout persistence with no backend is unsolved. Candidates considered and recorded: `localStorage` (per-browser, lost on other devices), an exported `layout.json` committed to the repo (read-only, clunky), or a retained `lan/dashboard/layout` topic (shared and backend-free, but requires a writable mosquitto user and gives up the read-only posture Phase 11's D-01 safety argument rests on).

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10 → 11 → 12 → 13

| Phase | Plans Complete | Status | Completed |
|-------|-----------------|--------|-----------|
| 8. Broker Infrastructure Hardening | 0/3 | Not started | - |
| 9. Poller Core | 4/4 | Complete   | 2026-09-09 |
| 10. Checkmk Tag-Group & Onboarding Integration | 6/6 | Complete   | 2026-09-11 |
| 11. Live Dashboard | 9/9 | Complete   | 2026-09-16 |
| 12. Agent Metrics and Service Status | 0/TBD | Not started | - |
| 13. Wizard Parents Support and Topology Map | 0/TBD | Not started | - |

### Phase 11.1: Dashboard Layout and Light Palette

**Goal**: The dashboard adopts KONE's light palette and the operator's three-pane layout, so the product looks and behaves the way it is meant to before any further capability is built on it
**Depends on**: Phase 11
**Requirements**: DASH-01 (re-worded 2026-09-16 per D-25/D-27 — see REQUIREMENTS.md), DASH-06
**Scope**: see `.planning/phases/11-live-dashboard/11.1-SCOPE.md` for the full brief.

Summary:
  1. KONE light palette, lifted from the contrast-audited preview override. Sourced from KONE's own `design-tokens.json`; every text pair >= 4.5:1 and every non-text mark >= 3.0:1, demonstrated by a computed audit
  2. Three panes — tree (left, full height), map-or-details (centre top), event history (centre bottom). `#sidebar-events` leaves the sidebar
  3. All three panes resizable and collapsible (not yet designed — see the scope doc's open questions on persistence and keyboard operability)
  4. The "Group by type" toggle becomes a select (`type` / `folder`, extensible) plus an "Order by severity" checkbox
  5. Verify newest-first event ordering against the live poller and add a regression test. The shipped code is already correct; the reported fault was in the preview harness

**Revises**: D-22 (dark, split sidebar) and D-24 (index = stats strip + grouped overview) must be formally superseded in `11-CONTEXT.md`, not silently ignored. D-11's colour *meanings* stand; only the values are re-derived.

**Requirements note (RESOLVED 2026-09-16)**: DASH-01 has been re-worded — "a grouped fleet overview" became "the centre's primary view", with the topology map named as that view and a sized placeholder standing in until Phase 13 (DASH-07) lands. The stats strip, the "above", and the merge-in-place clause survive verbatim, so this was a re-wording, not a re-scope. See `.planning/REQUIREMENTS.md` (re-wording note) and D-27 in `.planning/phases/11.1-dashboard-layout-and-light-palette/11.1-CONTEXT.md`.

**Explicitly out of scope**: everything in Phase 14, plus the Phase 12 and 13 mockups present in the working preview. Those are illustrative only.

**Plans**: 11 plans
Plans:
**Wave 1**

- [x] 11.1-01-PLAN.md — Supersede Phase 11's D-22/D-24 in `11-CONTEXT.md`; confirm DASH-01's re-wording (D-36)
- [x] 11.1-02-PLAN.md — Verify newest-first event ordering against the live poller; pin it with two pytest regression tests (D-33)
- [x] 11.1-03-PLAN.md — KONE light palette in the vanilla dashboard (D-28, D-29, D-38, D-39) — *superseded by the 2026-09-21 React pivot (D-40/D-43); shipped, not extended*

*Plans 04-11 below were replanned on 2026-09-21 for the React pivot (D-40-D-46). The original waves 2-7 (contrast-audit script, vanilla three-pane layout, `panes.js`, vanilla grouping controls, vanilla stale-flip fix, `dashboard/README.md`) are dropped: D-43 supersedes the technology and keeps the product behavior, which is now delivered in `dashboard-react/`.*

**Wave 1 (React)**

- [x] 11.1-04-PLAN.md — `dashboard-react/` scaffold: Vite + React 19 + TS + Tailwind v3, kone-design-system via packed tarball, react-router v8 Declarative Mode, vitest harness, `src/lib/config.ts` (D-40, D-41, D-37)

**Wave 2** *(blocked on 11.1-04)*

- [x] 11.1-05-PLAN.md — Ported logic (`display`/`staleness`/`grouping`), Zustand store with wholesale-replace slices, mqtt.js singleton with jittered backoff (D-46, DASH-05)
- [x] 11.1-06-PLAN.md — Custom `Splitter` with the full ARIA separator contract, `usePaneLayout` guarded persistence, three-pane grid, sized map placeholder (D-26, D-25, D-27, D-31, D-45)

**Wave 3** *(blocked on Wave 2)*

- [x] 11.1-07-PLAN.md — Device-state -> `Badge` mapping, stats strip above the map placeholder, `StatusBadge` connection indicator, MQTT bootstrap (D-44, D-11, DASH-01)

**Wave 4** *(blocked on Wave 3)*

- [x] 11.1-08-PLAN.md — `treeModel` + custom multi-open severity-aware `Tree`/`TreeNode`, device-type icons, folder grouping (D-45, DASH-06)

**Wave 5** *(blocked on Wave 4)*

- [x] 11.1-09-PLAN.md — Extensible grouping `<select>` + "Order by severity" checkbox, severity ordering derived per render, expansion survives a re-sort (D-32)

**Wave 6** *(blocked on Wave 5)*

- [x] 11.1-10-PLAN.md — Newest-first event history with a consumer-side ordering regression test, middle-truncated device identification (D-33, D-35)

**Wave 7** *(blocked on Wave 6)*

- [x] 11.1-11-PLAN.md — `useNowTick` clock, D-34 stale-stability regression suite, `dashboard-react/README.md` + deployment-doc `CHECKMK_BASE_URL` callout and nginx `try_files` cutover note, human verification (D-34, D-37, D-41, D-42)

### Phase 14: Fleet Intelligence

**Goal**: The dashboard stops reporting device status and starts reporting service impact, cause, and forecast
**Depends on**: Phase 11.1; root-cause collapse additionally depends on Phase 13; prediction additionally depends on Phase 12
**Requirements**: TBD — to be defined in REQUIREMENTS.md before planning
**Scope** (from the 2026-09-16 feature discussion; see the shared proposal for the full argument):

  1. **Service-impact framing** — the unit of measurement changes from devices to services. "sw-edge-tower-b is DOWN" becomes "Tower B: six lift systems unreachable, 12 minutes". Presentation work over data that already exists
  2. **Root-cause collapse** — one switch failure renders as ONE incident with its downstream devices shown as consequences, not seven independent alarms. Uses the DOWN-vs-UNREACHABLE distinction already captured in `host_state_raw` (D-17). Needs Phase 13's `parents`
  3. **Kiosk / wall mode** — full-screen, chrome-free, auto-rotating. Cheap; high value for a lobby or boardroom screen
  4. **Availability reporting on MinIO** — the poller writes one small daily rollup object per day (availability, incident count, mean recovery, per device and per location). A few hundred small objects a year. No new database and no new container, and it answers the quarterly-availability question on its own
  5. **Time-series store + Grafana** — when per-metric history is wanted, add a TSDB that uses the already-deployed MinIO as its long-term tier, and point Grafana at it. Grafana sits ALONGSIDE the dashboard (analyst tool vs at-a-glance operational view), not instead of it
  6. **Failure prediction** — fit a trend to a monotonic metric, extrapolate to threshold, report a date. Filesystem growth, SSD/NVMe wear, reallocated sectors, memory creep. No ML in v1; simple regression keeps the answer explainable, which matters when it justifies dispatching an engineer
  7. **AI incident narration** — the system writes the incident summary a human would, published to a retained MQTT topic by the poller so the dashboard stays a pure consumer and no backend is added

**Critical edition finding (verified against Checkmk docs 2026-09-16)**: Checkmk's own export to external metric databases (InfluxDB, Graphite) is a **commercial-edition** feature; **Grafana integration is available in all editions**. This site runs 2.4.0p36.**cre** (Raw). Therefore Checkmk cannot push metrics into a TSDB here — **our own poller must write them**. It already reads Livestatus and begins parsing `perf_data` in Phase 12, so this is a small addition to a component that exists. A second reason to own the history: Checkmk's built-in RRD storage downsamples as data ages by design, which is fine for "was it busy last Tuesday" and useless for "what is the slope of this drive's wear over three years".

**Open decisions blocking planning**:
  - May monitoring data leave the network? Blocks any external-model narration. If no, a local model or template-based narration gets most of the effect and never invents a fact
  - Is the Checkmk edition fixed at Raw? Confirms our-own-pipeline as the only path
  - Retention target for history — sizes the store and sets how far predictions can reach
  - Who is Grafana for? Decides whether it sits alongside the dashboard or replaces it

**Honest caveat to carry**: a projection is only as good as its history. Disk-fill dates are credible almost immediately; a drive-failure date is not credible until the drive has been watched for months. Promising it sooner is the one thing that would undermine the rest.

**Plans**: TBD
