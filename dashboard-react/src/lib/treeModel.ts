// Group and device tree nodes derived from store state, shaping the results of
// grouping.ts's own primitives (buildGroupIndex/rollUpGroup/sortedGroupKeys) for rendering.
// This module does not re-derive severity ordering or group-key logic -- both already live
// in grouping.ts, and D-32/D-43 name reusing them verbatim as a binding constraint. Ported
// from dashboard/js/render-shell.js's renderTree()/groupElement()/hostRowElement() data
// shaping (not their DOM manipulation).
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import { buildGroupIndex, rollUpGroup, sortedGroupKeys } from "./grouping";
import { deviceTypeIcon, displayName, effectiveState, isTagGroupMissing } from "./display";
import { isDeviceStale } from "./staleness";
import type { DevicePayload, GroupingMode } from "./types";

export interface TreeDeviceNode {
  kind: "device";
  id: string;
  label: string;
  state: string;
  stale: boolean;
  typeIcon: string;
  tagGroupMissing: boolean;
}

export interface TreeGroupNode {
  kind: "group";
  key: string;
  label: string;
  worst: string;
  worstRank: number;
  nonOkCount: number;
  total: number;
  hatched: boolean;
  children: TreeDeviceNode[];
}

export function buildTree(
  devices: Record<string, DevicePayload>,
  mode: GroupingMode,
  nowMs: number = Date.now(),
): TreeGroupNode[] {
  // grouping.ts's primitives take a Map (its vanilla signature, unchanged); the store holds a
  // plain Record for Zustand selector equality. This conversion is the one intentional
  // adapter point between the two -- no other module should need to bridge these shapes.
  const devicesMap = new Map(Object.entries(devices ?? {}));
  const index = buildGroupIndex(devicesMap, mode);

  // Sort order is derived here on every call, never cached -- D-32's binding constraint is
  // that sort order is computed from current state on each rebuild.
  return sortedGroupKeys(index).map((key) => {
    const ids = index.get(key) ?? new Set<string>();
    const rollup = rollUpGroup(ids, devicesMap, nowMs);

    const children: TreeDeviceNode[] = [...ids]
      .map((id) => {
        const device = devicesMap.get(id);
        return {
          kind: "device" as const,
          id,
          label: displayName(device),
          state: effectiveState(device),
          stale: isDeviceStale(device, nowMs),
          typeIcon: deviceTypeIcon(device?.device_type),
          tagGroupMissing: isTagGroupMissing(device),
        };
      })
      .sort((a, b) => a.label.localeCompare(b.label));

    return {
      kind: "group" as const,
      key,
      label: key,
      worst: rollup.worst,
      worstRank: rollup.worstRank,
      nonOkCount: rollup.nonOkCount,
      total: rollup.total,
      hatched: rollup.hatched,
      children,
    };
  });
}
