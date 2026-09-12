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
