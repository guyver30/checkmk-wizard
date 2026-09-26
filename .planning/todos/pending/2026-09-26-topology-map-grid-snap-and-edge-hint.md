---
created: 2026-09-26T00:00:00.000Z
title: Topology map grid with snap-to-grid, and an edge-direction hint in edit mode
area: dashboard
files:
  - dashboard-react/src/components/TopologyMap.tsx (arrows: "to" ~line 91, dragEnd -> setMapPosition, addEdge)
  - dashboard-react/src/components/TopologyToolbar.tsx (edit-mode UI, where the hint could live)
  - dashboard-react/src/lib/topologyLayout.ts (map_position label format)
---

## Problem

Requested by the operator during Phase 14's 14-05 live UAT (2026-09-26):

1. The network map has no grid, so hosts are hard to line up. Wanted: a visible grid on the map
   and hosts snapping to it when dragged (the snapped position is what gets saved as the
   `map_position` label via `setMapPosition`).
2. When drawing an edge in edit mode it is not obvious which way it goes. The arrow points
   parent -> child; the operator assumed it pointed to the parent.

## Decision (operator, 2026-09-26)

- Keep the arrow parent -> child (conventional topology direction). Add an edit-mode hint, e.g.
  "Drag from the parent (uplink) to the child device", shown while drawing edges.
- Do it as a `/bm:quick` task AFTER Phase 14 completes. Plan 14-08 edits TopologyMap.tsx, so
  doing it earlier would collide.

## Notes

- Grid spacing: pick a sensible default (e.g. match the existing auto-layout grid spacing in
  topologyLayout.ts if one exists); no configurability unless asked.
- Snap on dragEnd before the position write, so saved positions are already on the grid.
- Existing saved positions that are off-grid: leave as-is until the node is next moved.
