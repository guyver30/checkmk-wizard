// Group and device tree nodes derived from store state, shaping the results of
// grouping.ts's own primitives (buildGroupIndex/rollUpGroup/sortedGroupKeys) for rendering.
// This module does not re-derive severity ordering or group-key logic -- both already live
// in grouping.ts, and D-32/D-43 name reusing them verbatim as a binding constraint. Ported
// from dashboard/js/render-shell.js's renderTree()/groupElement()/hostRowElement() data
// shaping (not their DOM manipulation).
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import { buildGroupIndex, rollUpGroup, sortedGroupKeys, SEVERITY_RANK } from "./grouping";
import { displayName, effectiveState, isTagGroupMissing } from "./display";
import { isDeviceStale } from "./staleness";
import type { IncidentLookup } from "./incidents";
import type { DevicePayload, GroupingMode } from "./types";

export interface TreeDeviceNode {
  kind: "device";
  id: string;
  label: string;
  state: string;
  stale: boolean;
  deviceType: string | null | undefined;
  tagGroupMissing: boolean;
  dimmed: boolean;
  incidentId: string | null;
  incidentRole: "root" | "consequence" | null;
  inferredRoot: boolean;
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

export interface BuildTreeOptions {
  orderBySeverity?: boolean;
  // Plain parameter, never a store read -- same rule this file's header comment states for
  // orderBySeverity. Callers (IndexRoute, plan 14-04) pass the current incident lookup on
  // every render; buildTree never subscribes to incident state itself.
  incidentLookup?: IncidentLookup;
}

export function buildTree(
  devices: Record<string, DevicePayload>,
  mode: GroupingMode,
  nowMs: number = Date.now(),
  // `options` is a plain parameter, not component state -- callers (IndexRoute) pass the
  // current checkbox value on every render, so sort order is always derived from current
  // state rather than cached across rebuilds. This is what satisfies D-32's "sort order must
  // be derived on each rebuild, never held in the DOM/component state" constraint structurally:
  // there is nowhere in this module for a stale order to be kept.
  options: BuildTreeOptions = {},
): TreeGroupNode[] {
  const { orderBySeverity = false, incidentLookup } = options;

  // grouping.ts's primitives take a Map (its vanilla signature, unchanged); the store holds a
  // plain Record for Zustand selector equality. This conversion is the one intentional
  // adapter point between the two -- no other module should need to bridge these shapes.
  const devicesMap = new Map(Object.entries(devices ?? {}));
  const index = buildGroupIndex(devicesMap, mode);

  // Sort order is derived here on every call, never cached -- D-32's binding constraint is
  // that sort order is computed from current state on each rebuild.
  const groups: TreeGroupNode[] = sortedGroupKeys(index).map((key) => {
    const ids = index.get(key) ?? new Set<string>();
    const rollup = rollUpGroup(ids, devicesMap, nowMs);

    const children: TreeDeviceNode[] = [...ids]
      .map((id) => {
        const device = devicesMap.get(id);
        const membership = incidentLookup?.get(id);
        return {
          kind: "device" as const,
          id,
          label: displayName(device),
          state: effectiveState(device),
          stale: isDeviceStale(device, nowMs),
          deviceType: device?.device_type,
          tagGroupMissing: isTagGroupMissing(device),
          dimmed: membership?.role === "consequence",
          incidentId: membership?.incidentId ?? null,
          incidentRole: membership?.role ?? null,
          inferredRoot: membership !== undefined && membership.role === "root" && membership.inferred,
        };
      })
      .sort((a, b) => a.label.localeCompare(b.label));

    if (orderBySeverity) {
      // Devices within a group order by descending severity rank of their already-derived
      // state, then alphabetically -- SEVERITY_RANK is imported verbatim from grouping.ts,
      // never restated here (D-32's second binding constraint).
      children.sort((a, b) => {
        const rankDiff =
          (SEVERITY_RANK[b.state] ?? SEVERITY_RANK.UNKNOWN) -
          (SEVERITY_RANK[a.state] ?? SEVERITY_RANK.UNKNOWN);
        return rankDiff !== 0 ? rankDiff : a.label.localeCompare(b.label);
      });
    }

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

  if (orderBySeverity) {
    // Groups order by descending worstRank, then descending nonOkCount, then alphabetically
    // as the final, deterministic tie-break -- both worstRank and nonOkCount are already
    // produced by rollUpGroup above, so this is a sort, not a second severity computation.
    groups.sort((a, b) => {
      if (b.worstRank !== a.worstRank) return b.worstRank - a.worstRank;
      if (b.nonOkCount !== a.nonOkCount) return b.nonOkCount - a.nonOkCount;
      return a.label.localeCompare(b.label);
    });
  }

  return groups;
}
