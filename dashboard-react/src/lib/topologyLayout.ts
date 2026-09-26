// Turns the poller's raw topology device list plus current device statuses into the node/edge
// model the topology map renders, and computes initial grid positions for hosts with no saved
// `map_position` yet. Mirrors the STALE-overrides-state rule already used by
// store/selectors.ts's selectStateCounts and treeModel.ts's buildTree, and reuses
// display.ts's displayName()/effectiveState() rather than re-deriving them.
//
// D-11 forward-compatibility: buildMapModel takes an already-filtered device list as a plain
// parameter and never reads the store. A later tag-filter pass (Phase 15) can narrow the input
// list before calling this function; this function itself does not change.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import { displayName, effectiveState } from "./display";
import { isDeviceStale } from "./staleness";
import type { IncidentLookup } from "./incidents";
import type { DevicePayload } from "./types";

// Checkmk host-label keys shared by the poller (plan 13-04) and the browser's direct-write
// client (plan 13-05) -- both consumers must use these exact strings.
export const MAP_POSITION_LABEL = "map_position";
export const UNMANAGED_SWITCH_LABEL = "unmanaged_switch";
export const UNMANAGED_SWITCH_VALUE = "yes";
export const GRID_SPACING = 150;

const MAP_POSITION_RE = /^-?\d{1,6},-?\d{1,6}$/;

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

  const nodes: MapNode[] = validEntries.map((entry) => {
    const status = safeStatuses[entry.id];
    const state = isDeviceStale(status, nowMs) ? "STALE" : effectiveState(status);
    const label = status ? displayName(status) : displayName({ id: entry.id, alias: entry.alias });
    const membership = incidentLookup.get(entry.id);
    return {
      id: entry.id,
      label,
      deviceType: entry.device_type,
      state,
      position: parseMapPosition(entry.map_position),
      unmanaged: entry.unmanaged === true,
      dimmed: membership?.role === "consequence",
      incidentId: membership?.incidentId ?? null,
      incidentRole: membership?.role ?? null,
      inferredRoot: membership !== undefined && membership.role === "root" && membership.inferred,
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
