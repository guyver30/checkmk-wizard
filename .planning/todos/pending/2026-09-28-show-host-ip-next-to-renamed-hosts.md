---
created: 2026-09-28T00:00:00.000Z
title: Show a host's IP address next to its name when the name is not the IP
area: poller + dashboard
files:
  - scripts/mqtt_poller.py (Livestatus hosts query: add the `address` column to device/topology payloads)
  - dashboard-react/src/lib/types.ts, dashboard-react/src/lib/display.ts (IP-suffix helper)
  - dashboard-react/src/components/Tree.tsx (hover tooltip)
  - dashboard-react/src/components/IncidentList.tsx (incident cards)
  - dashboard-react/src/components/TopologyMap.tsx (node labels)
  - dashboard-react/src/components/EventHistory.tsx (event rows)
---

## Problem

Requested by the operator during Phase 14's 14-09 live UAT (2026-09-28): when a host's name
isn't its IP address (renamed during the wizard, e.g. `router`, `pve`, `e-linkWKS`), the dashboard
shows only the name and the IP can't be seen anywhere.

## Wanted

- Device tree: show the IP as a tooltip when hovering over the name.
- Incident cards, topology map, event history: always show the IP in brackets after the name,
  e.g. `router (192.168.0.1)`.

## Notes

- The poller doesn't publish the IP address today. Livestatus `hosts` has an `address` column,
  and the host check output (`router: 192.168.0.1 rta ...`) shows Checkmk already knows it.
- Assumed rule: add the IP whenever the displayed name (alias, or else the id) isn't equal to the
  address. That also covers an IP-named host that has a human alias. Confirm with the operator.
- Unmanaged switches (Phase 13 "Add node") have no IP, so show no suffix.
- A payload without `address` (from an older poller) must render exactly as today.
- Do it after Phase 14 completes, as a `/bm:quick` task. It touches TopologyMap.tsx, like the grid/snap todo, so run them one after the other.
