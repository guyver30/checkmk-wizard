# Phase 14: Fleet Intelligence - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning (Phase 14 proper only; 14.1 and 14.2 are recorded as locked inputs, not planned)

<domain>
## Phase Boundary

ROADMAP.md bundled seven features into Phase 14. This discussion **split it into three phases** (D-01):

- **Phase 14 (this context)** — service-impact / root-cause framing, criticality and dependency model, kiosk/wall mode. Presentation over data the poller already reads, plus a label write path for criticality and dependencies.
- **Phase 14.1 (to be inserted)** — history: TSDB on MinIO, availability rollups on MinIO, Grafana. Poller writes history.
- **Phase 14.2 (to be inserted)** — failure prediction and incident narration, in a separate analytics container.

Decisions for 14.1 and 14.2 below (D-20..D-31) are locked inputs so those phases don't re-ask; they are not detailed designs.

</domain>

<decisions>
## Implementation Decisions

### Scope slicing
- **D-01:** Three phases: 14 (impact, root-cause, kiosk), 14.1 (history + availability + Grafana), 14.2 (prediction + AI narration). Numbered as decimals; Phase 15 (location) is not renumbered.
- **D-02:** Availability reporting on MinIO (roadmap feature 4) belongs to 14.1, with the TSDB, because both share the poller-writes-history plumbing and the retention decision.
- **D-03:** The four blocking decisions from ROADMAP.md are resolved here (D-20, D-21, D-22, D-23) so no phase is blocked on them.

### Impact framing: what it may and may not claim
- **D-04:** Impact is NOT derived from `device_type`. An UNREACHABLE device behind a dead unmanaged switch may still be operating (only unobservable); a genuinely DOWN device is more serious. The UI must distinguish "not observable (upstream cause)" from "confirmed down" and never assert "lift not operating" from monitoring data alone.
- **D-05:** Criticality is business knowledge that Checkmk does not have. It is entered by an operator, never inferred. Examples given: a multimedia server outranks a multimedia screen; some Linux services matter more than others.
- **D-06:** Scope is the largest option: evidence framing **plus** per-host criticality **plus** dependency links ("depends on", e.g. screen -> media server). This is a deliberately large scope for the phase; the planner should wave it so evidence framing (root-cause collapse) ships and is verifiable before criticality/dependency editing.

### Storage and editing of the impact model
- **D-07:** Criticality tier and dependency links are stored as **Checkmk host labels** written via REST from the dashboard's edit mode, carried to every viewer by the poller. This is the Phase 13 pattern (map-position label, unmanaged-switch marker; `MAP_POSITION_LABEL` / `UNMANAGED_SWITCH_LABEL` in `scripts/mqtt_poller.py`). No new store, survives dashboard redeploy.
- **D-08:** Per-service criticality (e.g. a systemd service on a Linux host) is a label on the host keyed by service name.
- **D-09:** Exact tier vocabulary (names and count of tiers), label key names and the dependency label encoding are Claude's discretion, subject to Checkmk label constraints (research must verify label value length/charset against the live 2.4.0p36 site).

### Root cause and incident rendering
- **D-10:** Root-cause collapse uses Phase 13's `parents` plus the DOWN vs UNREACHABLE distinction already in `host_state_raw` (Phase 11 D-17).
- **D-11:** When a device is DOWN and its parent is an **unmanaged** switch (unobservable), treat the unmanaged parent as the **inferred** root cause, labelled "inferred, not confirmed". If several siblings under it go down together it is one incident; a single device down alone with no sibling evidence is its own incident.
- **D-12:** Rendering: a top-of-dashboard **incident card list** (one card per root cause: duration, consequences grouped into "not observable" vs "confirmed down", worst criticality affected). In the device tree and map, consequence devices stay visible but are dimmed and point to the incident instead of raising their own alarm.
- **D-13:** Incident detection/grouping happens in the poller and is published to retained MQTT topics so the dashboard stays a pure MQTT consumer for this feature. Topic names are Claude's discretion; follow the `lan/devices/...` per-topic, change-only publishing conventions (PLR-04).

### Kiosk / wall mode
- **D-14:** Full-screen, chrome-free, auto-rotating view for a lobby or boardroom screen (roadmap feature 3). Not discussed in depth; details (rotation content, interval, URL switch such as `?kiosk`) are Claude's discretion, keeping to the KONE design system.

### Locked inputs for Phase 14.1 (history)
- **D-20:** Checkmk edition is fixed at **Raw (CRE)**; Checkmk's InfluxDB/Graphite export is a commercial feature, so the **poller writes metric history**. No abstraction layer for a hypothetical edition upgrade.
- **D-21:** Retention target: **3 years, downsampled** (raw resolution roughly 30 days, then downsampled out to 3 years). Sizes the store.
- **D-22:** Grafana is **alongside** the dashboard, **for analysts** (per-metric history). It does not replace dashboard views. Grafana is optional and can be skipped without losing anything operational.
- **D-23:** The history store is a TSDB container in the existing compose stack, with **MinIO as its long-term tier**; a local volume holds recent data. Availability rollups (one small object per day per device/location) are plain objects in MinIO. TSDB product choice is for the 14.1 researcher (candidates: VictoriaMetrics, Prometheus + long-term store, InfluxDB); it must run against MinIO's S3 API.
- **D-24:** The main dashboard reads history by **querying the TSDB over HTTP**, read-only. This **amends** the project constraint "no server-side application; state comes entirely from MQTT retained messages" (as Phase 11.1 D-40 amended the build-tooling half). **PROJECT.md and CLAUDE.md constraints must be updated when 14.1 is planned.** The access mechanism (nginx read-only proxy on the same origin, vs other) is left to 14.1 research; the principle is the Phase 8 read-only ACL: browsers may read, only the poller writes, and write/admin endpoints are not reachable.

### Locked inputs for Phase 14.2 (prediction and narration)
- **D-30:** Data egress for narration: **no monitoring data leaves the network**. Narration is template-based or a local model; it never states a fact not present in the incident data. An external model is out.
- **D-31:** Prediction is simple regression (no ML in v1) on monotonic metrics: filesystem growth, SSD/NVMe wear, reallocated sectors, memory creep. Dates are shown **immediately with a confidence tag** (low/medium/high by history length) rather than gated on a minimum history. **Risk to carry to planning:** a low-confidence drive-failure date could still trigger an engineer dispatch; the UI must make the confidence tag and history span prominent, and the roadmap's caveat (a drive-failure date is not credible until months of history) still applies.
- **D-32:** Forecast and narration are computed in a **separate analytics container** that reads the TSDB and publishes to retained MQTT topics; the poller stays small. (This differs from the roadmap's "published by the poller" wording for narration; the container publishes instead. The dashboard is still a pure MQTT consumer for these outputs.)
- **D-33:** (Added 2026-09-26, during Phase 14 planning.) Insights and predictions are consumed by technicians and experts as **service needs** in three tiers:
  - **Standard**: handled at scheduled maintenance. Covers deviations from standard operation that do not cause a shutdown but would cause issues if left unsolved (e.g. disk filling unusually fast, projected out of disk far enough ahead).
  - **Urgent**: the same kind of deviation, but projected to cause a serious problem within a short window (roughly 3 to 15 days).
  - **Immediate**: a failure that needs a technician dispatched now (e.g. a switch failing with many children unreachable, a Linux service stopped).
  Phase 14 does **not** implement any of this. Its incident cards stay as designed. Phase 14.2 owns the tier model, including mapping Phase 14 incidents and stopped services to "immediate".
- **D-34:** Tier boundaries are **operator-configurable** thresholds (days-to-threshold from the forecast), shipped with defaults of immediate < 3 days, urgent 3 to 15 days, standard > 15 days. The operator's first description used "at least 20 days" for standard; the configurable threshold covers that.
- **D-35:** An expert can **triage** a service need: downgrade urgent to standard, cancel it, or upgrade it to immediate. Where triage state is stored and how it is written is decided in Phase 14.2, alongside the prediction engine. Checkmk host labels are a poor fit for per-need, time-bound state.

### Claude's Discretion
- Tier names/count, label key and dependency encoding (D-09), MQTT topic names and payload shapes (D-13), kiosk details (D-14), incident card visual design within the KONE design system.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and history
- `.planning/ROADMAP.md` (Phase 14 entry, lines ~326-350) — original seven-feature scope, the Raw-edition finding, the honest caveat on prediction credibility
- `.planning/REQUIREMENTS.md` — Phase 14 requirements are TBD and must be minted before planning; PLR-04 (change-only publishing) and DASH-01 apply
- `.planning/PROJECT.md` — the "no new backend for the dashboard" constraint that D-24 amends (update it)

### Prior phase decisions this builds on
- `.planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md` — parents, unmanaged-switch check-free hosts (DASH-13), label-based storage, map edit mode and Apply flow (DASH-12, PLR-13)
- `.planning/phases/12-agent-metrics-and-service-status/12-CONTEXT.md` — services query, `perf_data` parsing, D-01/D-02 (disk and systemd service scope)
- `.planning/phases/11-live-dashboard/11-CONTEXT.md` — D-17 (`host_state_raw` DOWN vs UNREACH), MQTT topic contract
- `.planning/phases/11.1-dashboard-layout-and-light-palette/11.1-CONTEXT.md` — React/TS/Tailwind + kone-design-system pivot (D-40)
- `.planning/phases/08-broker-infrastructure-hardening/08-CONTEXT.md` — read-only WS ACL principle to reuse for TSDB access
- `.planning/phases/15-location-hierarchy-for-hosts-tower-building-sub-location-tag/` — location tags that could enrich incident wording later (not a dependency)

### Code
- `scripts/mqtt_poller.py` — Livestatus query layer, `host_state_raw`, `parents`, label parsing (`MAP_POSITION_LABEL`, `UNMANAGED_SWITCH_LABEL`), change-only publish helpers
- `dashboard-react/src/lib/types.ts` — payload types the dashboard consumes
- `device_types.json` — device type list (other, E-link, ACS, Multimedia, NetworkDevice, GroupController)
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — compose stack, topic contract (must be updated)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Poller host snapshot already carries `parents`, `host_state_raw`, `downtime`, `acknowledged`, worst service state and REST-sourced labels (`scripts/mqtt_poller.py`): the inputs root-cause grouping needs.
- Phase 13 label write path (dashboard edit mode -> REST -> poller -> all viewers) is the template for criticality and dependency editing.
- Existing event history and the `lan/events/recent` feed can carry incident open/close transitions.

### Established Patterns
- Change-only, per-device retained MQTT topics (`lan/devices/{id}/...`); new incident topics should follow suit.
- Dashboard is a pure MQTT consumer (Zustand wholesale-replace slices, mqtt.js singleton); a TSDB HTTP client in 14.1 is the first exception (D-24).
- Poller carries no persisted state and self-heals from Livestatus and broker-retained state; incident state should be derivable the same way.

### Integration Points
- Poller cycle: add incident computation after topology/parents are read.
- Dashboard: stats strip, tree, map (vis-network), edit mode.
- Compose stack: new TSDB and analytics containers in 14.1 / 14.2.

</code_context>

<specifics>
## Specific Ideas

- Operator's own framing: an unreachable group controller behind a down unmanaged switch is "still functioning, we just can't monitor it"; a really-down group controller means the lift is not operating and is more serious. Multimedia server offline is worse than one screen offline.
- Roadmap example wording to aim for where data allows: "Tower B: six lift systems unreachable, 12 minutes", but only as "not observable" unless confirmed down.

</specifics>

<deferred>
## Deferred Ideas

- Location-aware incident wording (tower/room) — arrives with Phase 15 location tags.
- Operator-acknowledged root cause per incident (manual choice of cause) — rejected for now in favour of inference (D-11).
- Local LLM for narration — optional later upgrade over templates (D-30).
- Checkmk-native metric export if the site ever moves off Raw — explicitly not designed for (D-20).

</deferred>

---

*Phase: 14-fleet-intelligence*
*Context gathered: 2026-09-26*
