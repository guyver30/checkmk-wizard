# Phase 11: Live Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `11-CONTEXT.md` — this log preserves how they were reached.

**Date:** 2026-09-12
**Phase:** 11-live-dashboard
**Mode:** discuss (default, interactive)
**Areas discussed:** Broker connection & credentials; Topology visual encoding; Staleness &
degraded states; Page shell, routing & Checkmk links

## Pre-discussion notes

- Operator was first offered a choice at plan-phase's no-CONTEXT gate and chose to run
  discuss-phase before planning.
- ROADMAP's progress table lists Phase 8 as "0/3 Not started", but Phase 8 has 3/3 SUMMARY.md
  files and its artifacts (`deploy/mosquitto.conf` WS listener, `deploy/compose.yaml` port 9002)
  are on disk. Stale bookkeeping — no VERIFICATION.md was ever written. Flagged to the operator;
  Phase 11 is not blocked.
- Operator asked mid-selection that `docs/DMC-networkmap.png` and `docs/DMC-server.png` be read
  for layout ideas. Both were read. They are AI-generated mockups with garbled text; only their
  layout language was treated as input.

## Area 1 — Broker connection & credentials

| Question | Options presented | Selected |
|---|---|---|
| Where do WS credentials live? | `js/config.js` checked in (rec.) / fetched `config.json` gitignored / login prompt + localStorage | **`js/config.js` checked in** |
| How is broker host:port determined? | Derive from `location.hostname` (rec.) / fully explicit in config | **Derive from `location.hostname`** |
| vis-network + mqtt.js — CDN or vendored? | Vendor into `js/vendor/` (rec.) / load from cdnjs | **Vendor** |
| nginx host port | 8081 (rec.) / 80 / 8090 | **8090** |

Notes: operator went against the recommendation on port only — 8090 keeps the dashboard
visually clear of the Checkmk 80xx cluster.

## Area 2 — Topology visual encoding

| Question | Options presented | Selected |
|---|---|---|
| state / device_type / folder → visual channels | color=state+icon=type+folder hull (rec.) / color=type+halo=state / folder in sidebar only | **Other** — operator redefined the area |
| Parentless hosts | Synthetic folder-root (rec.) / free-floating / one network root | **Synthetic group-root** |
| Layout behaviour | Stabilize-then-freeze (rec.) / hierarchical / physics always on | **Stabilize-then-freeze** |
| Sidebar tree grouping | By folder (rec.) / by device_type / flat by state | **Other** — "either, as explained" |

Operator's freeform redefinition (became D-05/D-06/D-07): grouping is a **runtime toggle**
between folder and device_type; the group node's color is a roll-up of its children; when
grouped by folder each child shows a type icon; when grouped by type, folder is not shown.
Operator also asked what grey means — answered with the full state table, which later had to be
corrected (see Area 3).

### Area 2 follow-up

| Question | Options presented | Selected |
|---|---|---|
| Roll-up rule (operator's stated rule used opposite logic for yellow vs red) | Worst-of any-red (rec.) / literal all-red / worst-of + count badge | **Worst-of + count badge** |
| DOWN vs CRIT | Distinct shades (rec.) / same red / shade + shape change | **Other** — "can add an icon near the host that is down? you suggest" |
| Group-mode default & persistence | Folder + localStorage (rec.) / folder, resets / device_type | **Default device_type** |
| Does a group roll up stale children? | Stale never masks known-bad (rec.) / stale is worst / stale excluded | **Stale never masks known-bad** |

Claude's call on the open item: `⛔` prepended to the label (no icon font to vendor, renders in
map/tree/table alike, does not carry the signal through hue). Offered to swap for a real icon
font on request.

## Area 3 — Staleness & degraded states

First pass:

| Question | Selected |
|---|---|
| Device staleness threshold | **Other** — operator asked that Checkmk's own docs be consulted first |
| Poller-liveness threshold | Same 3× rule, global condition |
| Poller confirmed offline | Banner + hatch everything, keep last values |
| `device_type: "unknown"` | Site-config warning banner |

Research performed (WebFetch, https://docs.checkmk.com/latest/en/monitoring_basics.html):
- Staleness parameter is `Staleness value to mark hosts / services stale`
  (Setup ▸ General ▸ Global settings ▸ User interface), expressed as **n × check interval,
  default 1.5**.
- Checkmk's palette: OK green, WARN yellow, CRIT red, **UNKNOWN orange**, UNREACH orange,
  DOWN red, **PEND grey**.

This **corrected an earlier answer** given to the operator: grey had been described as covering
UNKNOWN. In Checkmk, UNKNOWN is orange and grey means "never yet polled" — much closer to our
derived stale state.

Second pass:

| Question | Options presented | Selected |
|---|---|---|
| Staleness factor vs the 60s poll interval | 3× = 180s (rec.) / 1.5× = 90s Checkmk-exact / 2× = 120s | **3× = 180s** |
| Adopt Checkmk's palette? | Yes, mirror (rec.) / own dark-tuned palette | **Mirror Checkmk** |
| Checkmk `staleness` + DOWN/UNREACH are in Livestatus but not in the payload | Defer both, stay a pure consumer (rec.) / extend the poller contract / extend DOWN-UNREACH only | **Extend the poller contract** |

The contract-extension choice was made against the recommendation, with the cost stated up front
(Phase 11 now edits `scripts/mqtt_poller.py` and its tests, and stops being a purely backend-less
consumer phase). Recorded as D-17.

## Area 4 — Page shell, routing & Checkmk links

| Question | Options presented | Selected |
|---|---|---|
| Display name | Alias else hostname (rec.) / hostname always / hostname + alias underneath | **Alias else hostname** |
| details.html routing | `?id=` query string (rec.) / hash fragment / sessionStorage | **Query string** |
| Checkmk deep-link base URL | In `js/config.js` (rec.) / poller publishes it / derive from location | **In `js/config.js`** |
| Shared shell with no build step | `js/shell.js` injects (rec.) / duplicate markup / single-page view switching | **Single-page view switching** |

### Area 4 follow-up — requirements conflict

The single-page choice would have left `devices.html` and `details.html` non-existent,
contradicting DASH-01/02/03 and the ROADMAP success criteria. Rather than record an override,
a third shape was offered:

| Question | Options presented | Selected |
|---|---|---|
| Three real files behaving as one app? | Three files + pushState-intercepted nav (rec.) / true SPA with override / plain three-page nav | **Three files + intercepted nav** |

Resolved as D-21 — satisfies the locked requirements literally while keeping one persistent MQTT
connection across in-app navigation.

## Deferred ideas raised

- CPU/RAM/Disk gauges, process table, 7-day graphs, congestion sparklines (from the mockups —
  no metrics in the poller contract; time-series explicitly Out of Scope)
- Sidebar search box (overlaps DASH2-02, already deferred to v2)
- nginx reverse-proxy of `/mqtt` for single-origin + TLS
- Per-service drill-down inside the dashboard (permanently out of scope — link out instead)

## Claude's discretion recorded

Color hex values, device_type→glyph mapping, table columns and default sort, event-row
formatting, minimap inclusion, nginx config shape, `js/vendor/` file naming, `shell.js` internal
layout, and the payload field names for the two D-17 additions.

---

# Second session — scope revision (2026-09-12)

Operator raised three items after CONTEXT.md was first committed.

## Raised

1. Agent-installed Linux/Windows workstations expose CPU, disk space, OS services and disk
   health; clicking a host should show those as gauges (per `docs/DMC-server.png`) plus service
   status. Service status should influence host color. Event history must be always visible.
2. The network map would have to be drawn manually, since automatic mapping is unavailable.
3. Rethink how views switch when clicking a host.

## Findings presented before asking anything

- **Already satisfied:** service state already drives host color. The poller pulls
  `worst_service_state` and folds it in via worst-of (Phase 9 D-08). Nothing to build.
- **Does not exist:** verified by reading `scripts/mqtt_poller.py` — `build_hosts_query()` issues
  only `GET hosts`; the `services` table is never queried. No per-service state, no
  `plugin_output`, no `perf_data` anywhere in the contract.
- **Conflict:** PROJECT.md Out of Scope contains "Duplicating Checkmk's own per-service
  drill-down UI in the new dashboard — link out to Checkmk's UI for full service-level detail
  instead". The request is that item. Raised explicitly rather than folded in silently.
- **Compounding:** this would be the third thing growing a phase originally sized as a pure
  consumer (after D-17).

## Decisions

| Question | Options presented | Selected |
|---|---|---|
| Sizing for agent metrics | Split: 11 ships, 12 adds metrics (rec.) / expand 11 / trim to service list only | **Split into Phase 12** |
| What is manual about the map | Positions+links in dashboard / positions only / teach wizard to set `parents` (rec.) | **Other — "postpone the map to another phase"** |

The map answer was a larger cut than the question anticipated — the map is DASH-01 and ROADMAP
success criterion #1. Flagged back to the operator, then followed up:

| Question | Options presented | Selected |
|---|---|---|
| What is index.html without a map | Stats strip + grouped overview (rec.) / fold into devices.html / placeholder panel | **Stats strip + grouped overview** |
| Do grouping toggle and roll-up survive | Survive, drive tree+overview (rec.) / move out with the map | **Survive** |
| Order of the new phases | 12 metrics, 13 parents+map (rec.) / reverse / park in backlog | **12 metrics, 13 parents+map** |
| Detail-view switching | In-place panel, shell mounted (rec.) / split view / full page swap | **In-place panel** |
| Event-history placement | Bottom-left under tree (rec.) / full-width strip / right rail | **Bottom-left under tree** |
| DASH-01 bookkeeping | Split it, strip stays / move wholesale / leave alone | **Split DASH-01** |

## Effect on decisions

- **Revised:** D-03 (vis-network no longer vendored here, mqtt.js only), D-22 (shell layout now
  specifies the split left column with always-visible event history)
- **Added:** D-23 (in-place detail panel), D-24 (index.html = stats strip + grouped overview)
- **Moved to the map phase:** D-08 (synthetic group-roots), D-09 (stabilize-then-freeze physics).
  Rationale preserved here so the map phase need not re-derive it.
- **Unchanged:** D-01, D-02, D-04, D-05, D-06, D-07, D-10 through D-21
