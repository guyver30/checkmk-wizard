// Turns the poller's raw topology device list plus current device statuses into the node/edge
// model the topology map renders, and computes initial grid positions for hosts with no saved
// `map_position` yet. Node state comes from display.ts's displayState() (STALE overrides state,
// and an unmanaged switch with no real state of its own reads UNMANAGED), the same helper
// store/selectors.ts's selectStateCounts and treeModel.ts's buildTree use.
//
// D-11 forward-compatibility: buildMapModel takes an already-filtered device list as a plain
// parameter and never reads the store. A later tag-filter pass (Phase 15) can narrow the input
// list before calling this function; this function itself does not change.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import { displayName, displayNameWithAddress, displayState, effectiveState } from "./display";
import { isDeviceStale } from "./staleness";
import type { IncidentLookup } from "./incidents";
import type { DevicePayload } from "./types";

// Checkmk host-label keys shared by the poller (plan 13-04) and the browser's direct-write
// client (plan 13-05) -- both consumers must use these exact strings.
export const MAP_POSITION_LABEL = "map_position";
export const UNMANAGED_SWITCH_LABEL = "unmanaged_switch";
export const UNMANAGED_SWITCH_VALUE = "yes";
export const GRID_SPACING = 150;
// A third of the auto-layout spacing: every auto-layout slot (GRID_SPACING) lands exactly on a
// grid intersection, while 50px gives enough resolution to line hosts up in a dense map (a
// 150px snap would be too coarse).
export const MAP_SNAP_SPACING = GRID_SPACING / 3;

const MAP_POSITION_RE = /^-?\d{1,6},-?\d{1,6}$/;

export function snapToGrid(value: number): number {
  // `+ 0` normalises a -0 result (e.g. snapping a small negative value to the origin) to 0, so
  // saved map_position labels and toEqual/toHaveBeenCalledWith assertions never see "-0".
  return Math.round(value / MAP_SNAP_SPACING) * MAP_SNAP_SPACING + 0;
}

export function parseMapPosition(value: unknown): { x: number; y: number } | null {
  if (typeof value !== "string" || !MAP_POSITION_RE.test(value)) {
    return null;
  }
  const [xRaw, yRaw] = value.split(",");
  return { x: Number(xRaw), y: Number(yRaw) };
}

export function formatMapPosition(x: number, y: number): string {
  return `${Math.round(x)},${Math.round(y)}`;
}

export function initialGridPositions(ids: string[]): Record<string, { x: number; y: number }> {
  const cols = Math.ceil(Math.sqrt(ids.length));
  const positions: Record<string, { x: number; y: number }> = {};
  ids.forEach((id, i) => {
    positions[id] = { x: (i % cols) * GRID_SPACING, y: Math.floor(i / cols) * GRID_SPACING };
  });
  return positions;
}

export interface MapNode {
  id: string;
  label: string;
  deviceType: string | undefined;
  state: string;
  position: { x: number; y: number } | null;
  unmanaged: boolean;
  dimmed: boolean;
  incidentId: string | null;
  incidentRole: "root" | "consequence" | null;
  inferredRoot: boolean;
  // For an unmanaged switch: "N of M devices behind it are up" / "No devices connected".
  hint: string | null;
}

export interface MapEdge {
  id: string;
  from: string;
  to: string;
}

interface RawTopologyEntry {
  id: string;
  parents: unknown;
  device_type?: string;
  folder?: string;
  alias?: string;
  map_position?: string | null;
  unmanaged?: boolean;
}

function isValidEntry(entry: unknown): entry is RawTopologyEntry {
  if (!entry || typeof entry !== "object") {
    return false;
  }
  const id = (entry as { id?: unknown }).id;
  return typeof id === "string" && id.length > 0;
}

export function unmanagedIdsFromTopology(topologyDevices: unknown): Set<string> {
  const ids = new Set<string>();
  if (!Array.isArray(topologyDevices)) {
    return ids;
  }
  for (const entry of topologyDevices) {
    if (isValidEntry(entry) && entry.unmanaged === true) {
      ids.add(entry.id);
    }
  }
  return ids;
}

function childrenHintText(total: number, up: number): string {
  if (total === 0) {
    return "No devices connected";
  }
  return total === 1
    ? `${up} of 1 device behind it is up`
    : `${up} of ${total} devices behind it are up`;
}

function isChildUp(
  child: DevicePayload | undefined,
  nowMs: number,
): boolean {
  if (!child || isDeviceStale(child, nowMs)) {
    return false;
  }
  const state = effectiveState(child);
  return state !== "DOWN" && state !== "UNREACH";
}

export function unmanagedChildrenHint(
  switchId: string,
  topologyDevices: unknown,
  statuses: Record<string, DevicePayload>,
  nowMs: number,
): string {
  const entries = Array.isArray(topologyDevices) ? topologyDevices : [];
  const safeStatuses = statuses && typeof statuses === "object" ? statuses : {};
  let total = 0;
  let up = 0;
  const seen = new Set<string>();
  for (const entry of entries) {
    if (!isValidEntry(entry) || seen.has(entry.id)) {
      continue;
    }
    seen.add(entry.id);
    if (Array.isArray(entry.parents) && entry.parents.includes(switchId)) {
      total += 1;
      if (isChildUp(safeStatuses[entry.id], nowMs)) {
        up += 1;
      }
    }
  }
  return childrenHintText(total, up);
}

export function buildMapModel(
  topologyDevices: unknown[],
  statuses: Record<string, DevicePayload>,
  nowMs: number,
  // Plain parameter, never a store read -- same rule this file's own D-11 forward-compat
  // comment states for topologyDevices/statuses. Callers (TopologyMap, plan 14-04) pass the
  // current incident lookup on every render.
  incidentLookup: IncidentLookup = new Map(),
): { nodes: MapNode[]; edges: MapEdge[] } {
  const entries = Array.isArray(topologyDevices) ? topologyDevices : [];
  const safeStatuses = statuses && typeof statuses === "object" ? statuses : {};

  // De-duplicate by id, keeping only the first occurrence, while preserving input order.
  const seenIds = new Set<string>();
  const validEntries: RawTopologyEntry[] = [];
  for (const entry of entries) {
    if (!isValidEntry(entry)) {
      continue;
    }
    if (seenIds.has(entry.id)) {
      continue;
    }
    seenIds.add(entry.id);
    validEntries.push(entry as RawTopologyEntry);
  }

  // Direct children per parent, computed once so the per-switch hint is O(n) overall.
  const childIdsByParent = new Map<string, string[]>();
  for (const entry of validEntries) {
    if (!Array.isArray(entry.parents)) {
      continue;
    }
    for (const parent of new Set(entry.parents)) {
      if (typeof parent === "string") {
        const list = childIdsByParent.get(parent) ?? [];
        list.push(entry.id);
        childIdsByParent.set(parent, list);
      }
    }
  }

  const nodes: MapNode[] = validEntries.map((entry) => {
    const status = safeStatuses[entry.id];
    const unmanaged = entry.unmanaged === true;
    const state = displayState(status, unmanaged, nowMs);
    let hint: string | null = null;
    if (unmanaged) {
      const childIds = childIdsByParent.get(entry.id) ?? [];
      const up = childIds.filter((id) => isChildUp(safeStatuses[id], nowMs)).length;
      hint = childrenHintText(childIds.length, up);
    }
    const label = status
      ? displayNameWithAddress(status)
      : displayName({ id: entry.id, alias: entry.alias });
    const membership = incidentLookup.get(entry.id);
    return {
      id: entry.id,
      label,
      deviceType: entry.device_type,
      state,
      position: parseMapPosition(entry.map_position),
      unmanaged,
      dimmed: membership?.role === "consequence",
      incidentId: membership?.incidentId ?? null,
      incidentRole: membership?.role ?? null,
      inferredRoot: membership !== undefined && membership.role === "root" && membership.inferred,
      hint,
    };
  });

  const edges: MapEdge[] = [];
  for (const entry of validEntries) {
    const parents = Array.isArray(entry.parents) ? entry.parents : [];
    for (const parent of parents) {
      if (typeof parent === "string" && seenIds.has(parent)) {
        edges.push({ id: `${parent}->${entry.id}`, from: parent, to: entry.id });
      }
    }
  }

  return { nodes, edges };
}

export function withGridPositions(
  nodes: MapNode[],
): Array<MapNode & { x: number; y: number; saved: boolean }> {
  const savedYs = nodes
    .filter((n) => n.position !== null)
    .map((n) => (n.position as { x: number; y: number }).y);
  const gridStartY = savedYs.length > 0 ? Math.max(...savedYs) + GRID_SPACING : 0;

  const unsavedIds = nodes.filter((n) => n.position === null).map((n) => n.id);
  const grid = initialGridPositions(unsavedIds);

  return nodes.map((n) => {
    if (n.position !== null) {
      return { ...n, x: n.position.x, y: n.position.y, saved: true };
    }
    const pos = grid[n.id];
    return { ...n, x: pos.x, y: pos.y + gridStartY, saved: false };
  });
}
