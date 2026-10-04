// Renders useAppStore's `topology` slot as a live, editable vis-network graph. Mounts the
// vis-network Network exactly once (physics stabilizes then freezes on first load) and merges
// every subsequent topology/status change into the existing node/edge DataSets via
// `.update()`/`.add()`/`.remove()` -- the whole-graph-replacement Network method is never called.
//
// The `editMode` prop gates both node-click navigation and vis-network's built-in manipulation
// toolbar: off, a click opens the overview's right-hand host details pane (?host=<id>) and
// dragging/drawing is disabled; on, the toolbar's addEdge/editEdge/deleteEdge/addNode callbacks
// write directly to Checkmk through the shared REST writer module and dragging a node persists
// its position. Every write applies immediately to Checkmk but is never activated from here --
// activating changes is a separate, explicitly triggered batch action owned by the toolbar UI
// that surrounds this component.
//
// Takes its device list as a prop rather than reading the store directly, so a future
// tag-filter pass can narrow the input list without changing this file.

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { DataSet } from "vis-data/peer";
import { Network } from "vis-network/peer";
import "vis-network/styles/vis-network.css";
import { Banner } from "kone-design-system";
import { nodeVisual, type NodeEmphasis } from "../lib/mapIcons";
import { isAdminMode } from "../lib/adminMode";
import { useAdminStore } from "../store/adminStore";
import { useMapFocusStore } from "../store/mapFocusStore";
import { createUnmanagedSwitch, isValidHostName, setMapPosition, updateParents } from "../lib/checkmkWrite";
import { hostHref, incidentHref, withSearchParam } from "../lib/searchLinks";
import {
  buildMapModel,
  MAP_SNAP_SPACING,
  snapToGrid,
  withGridPositions,
  type MapEdge,
  type MapNode,
} from "../lib/topologyLayout";
import type { IncidentLookup } from "../lib/incidents";
import type { TierLookup } from "../lib/needDisplay";
import type { DevicePayload } from "../lib/types";

export interface EditFailure {
  title: string;
  body: string;
}

export interface TopologyMapProps {
  topologyDevices: unknown[];
  statuses: Record<string, DevicePayload>;
  nowMs: number;
  editMode?: boolean;
  onEditSaved?: () => void;
  onEditFailed?: (failure: EditFailure) => void;
  incidentLookup?: IncidentLookup;
  // Worst service-need tier per host; drawn as a small dot at the node's top-right.
  tierLookup?: TierLookup;
  onSelectHost?: (id: string) => void;
}

// Shared by addEdge/editEdge/deleteEdge -- all three write via updateParents, so all three fail
// the same way.
const CONNECTION_FAILURE: EditFailure = {
  title: "Couldn't save that connection",
  body: "Checkmk rejected the update. Check that both devices still exist, then try again.",
};

const POSITION_FAILURE: EditFailure = {
  title: "Couldn't save that position",
  body: "Checkmk rejected the update. Check that the device still exists, then try again.",
};

const ADD_NODE_PROMPT = "Name for the new unmanaged switch (letters, digits, dot, dash, underscore):";
const INVALID_SWITCH_NAME_FAILURE: EditFailure = {
  title: "Couldn't add that switch",
  body: "Use letters, digits, dot, dash or underscore only.",
};
const DUPLICATE_SWITCH_NAME_FAILURE: EditFailure = {
  title: "Couldn't add that switch",
  body: "A device with that name already exists.",
};
const SWITCH_CREATE_FAILURE: EditFailure = {
  title: "Couldn't add that switch",
  body: "Checkmk rejected the new host. Check the name isn't already used, then try again.",
};

// 13-UI-SPEC.md Copywriting Contract -- verbatim.
const EMPTY_STATE_HEADING = "No connections drawn yet";
const EMPTY_STATE_BODY =
  "Every device is shown below, ready to connect. Turn on Edit topology and drag between two devices to draw a link — it saves to Checkmk once you Apply.";
const NO_CONNECTIONS_BANNER_MESSAGE = "No connections drawn yet — turn on Edit topology to start.";
const UNMANAGED_SWITCH_TITLE = "Unmanaged switch (not monitored)";
// DASH-15/14-UI-SPEC "Dimmed Consequence Treatment" -- replaces the unmanaged-switch title for
// a dimmed or inferred-root node; a plain unmanaged (non-root) node keeps its own title.
const DIMMED_NODE_TITLE = "Part of an open incident — click to see it";
const INFERRED_ROOT_TITLE = "Inferred root cause, not confirmed";

const ROOT_CLASS_NAME =
  "relative flex h-full w-full items-center justify-center rounded-md border border-neutral-150 bg-bg-subtle";

// D-01/D-05: the map hard-codes its palette (NETWORK_OPTIONS below) and has no theme tokens
// today, so the grid follows suit with one faint neutral hex close to the container's own
// border tone, rather than plumbing in a new theme concept.
const GRID_LINE_COLOR = "#ececef";

// Defensive cap (threat T-m6g-02): at extreme zoom-out the visible network-coordinate range can
// span an enormous number of grid lines; skip drawing rather than let that stall the canvas.
const MAX_GRID_LINES_PER_AXIS = 400;

// D-03: the arrow direction itself is unchanged (parent -> child); this hint just explains it
// while edit mode is on.
const EDGE_DIRECTION_HINT = "Drag from the parent (uplink) to the child device";

// Zoom controls (operator request 2026-09-28): each step multiplies or divides the current scale,
// clamped so the map can neither vanish nor blow up past usefulness. Fit uses vis-network's own
// fit(), which frames every node.
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const ZOOM_ANIMATION = { duration: 200, easingFunction: "easeInOutQuad" as const };

const ZOOM_BUTTON_CLASS =
  "flex h-8 w-8 items-center justify-center text-fg-secondary hover:bg-bg-subtle-hover hover:text-fg-primary";

function ZoomIcon({ kind }: { kind: "in" | "out" | "fit" }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {kind === "in" && <path d="M12 5v14M5 12h14" />}
      {kind === "out" && <path d="M5 12h14" />}
      {kind === "fit" && <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
    </svg>
  );
}

// Draws a faint grid across the currently visible canvas area, in network (canvas-space)
// coordinates. Called from vis-network's beforeDrawing hook, whose ctx is already transformed
// into those coordinates -- so drawing here pans and zooms with the map for free, with no
// per-frame bookkeeping of our own.
function drawGrid(ctx: CanvasRenderingContext2D, network: Network, container: HTMLElement): void {
  const topLeft = network.DOMtoCanvas({ x: 0, y: 0 });
  const bottomRight = network.DOMtoCanvas({ x: container.clientWidth, y: container.clientHeight });
  const minX = Math.floor(topLeft.x / MAP_SNAP_SPACING) * MAP_SNAP_SPACING;
  const maxX = Math.ceil(bottomRight.x / MAP_SNAP_SPACING) * MAP_SNAP_SPACING;
  const minY = Math.floor(topLeft.y / MAP_SNAP_SPACING) * MAP_SNAP_SPACING;
  const maxY = Math.ceil(bottomRight.y / MAP_SNAP_SPACING) * MAP_SNAP_SPACING;

  const columnCount = (maxX - minX) / MAP_SNAP_SPACING;
  const rowCount = (maxY - minY) / MAP_SNAP_SPACING;
  if (columnCount > MAX_GRID_LINES_PER_AXIS || rowCount > MAX_GRID_LINES_PER_AXIS) {
    return;
  }

  ctx.save();
  ctx.strokeStyle = GRID_LINE_COLOR;
  // Keep the stroke about 1px wide on screen regardless of zoom, since ctx is in
  // network (post-zoom) coordinates here.
  ctx.lineWidth = 1 / network.getScale();
  ctx.beginPath();
  for (let x = minX; x <= maxX; x += MAP_SNAP_SPACING) {
    ctx.moveTo(x, minY);
    ctx.lineTo(x, maxY);
  }
  for (let y = minY; y <= maxY; y += MAP_SNAP_SPACING) {
    ctx.moveTo(minX, y);
    ctx.lineTo(maxX, y);
  }
  ctx.stroke();
  ctx.restore();
}

// Fallback for canvas drawing when the CSS variable cannot be resolved (canvas cannot use
// var(...) directly, so the token is read once per frame from the container's computed style).
const TIER_MARKER_FALLBACK_COLOR = "#f59e0b";
const TIER_MARKER_RADIUS = 4;
// Offset from the node centre to its top-right, in canvas units (node size is 16).
const TIER_MARKER_OFFSET = 12;

// Draws the service-need tier marker (filled dot immediate, ring urgent) at each node's
// top-right, in network coordinates (called from afterDrawing, so it pans and zooms with the
// map). It sits on top of the node and never changes the node's own colour or border.
function drawTierMarkers(
  ctx: CanvasRenderingContext2D,
  network: Network,
  container: HTMLElement,
  tierLookup: TierLookup,
): void {
  const ids = Object.keys(tierLookup).filter((id) => tierLookup[id].tier !== "standard");
  if (ids.length === 0) {
    return;
  }
  const positions = network.getPositions(ids);
  const resolved = getComputedStyle(container).getPropertyValue("--color-warning-default").trim();
  const color = resolved || TIER_MARKER_FALLBACK_COLOR;
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  for (const id of ids) {
    const position = positions[id];
    if (!position) {
      continue;
    }
    ctx.beginPath();
    ctx.arc(
      position.x + TIER_MARKER_OFFSET,
      position.y - TIER_MARKER_OFFSET,
      TIER_MARKER_RADIUS,
      0,
      2 * Math.PI,
    );
    if (tierLookup[id].tier === "immediate") {
      ctx.fill();
    } else {
      ctx.stroke();
    }
  }
  ctx.restore();
}

// 13-UI-SPEC.md "Topology Map Rendering" -- node/edge/physics/interaction options, locked.
const NETWORK_OPTIONS = {
  nodes: {
    shape: "circularImage",
    size: 16,
    font: { face: "Inter", size: 12, color: "#111114" },
  },
  edges: {
    arrows: "to",
    color: { color: "#96969f", highlight: "#1450f5", hover: "#1450f5" },
    width: 1,
  },
  physics: { stabilization: { iterations: 200 } },
  interaction: { dragNodes: false, hover: true },
  manipulation: { enabled: false },
  layout: { randomSeed: 1 },
};

// Fields shared by nodes.update() (existing node) and nodes.add() (new node) -- NO x/y here,
// so an update never disturbs a dragged/panned/zoomed position (Phase 11 D-09).
// Canvas cannot read CSS variables: same hex as the existing highlight border and the index.css
// brand colour (UI-SPEC Color rules).
const SELECTED_BORDER_HEX = "#1450f5";

interface AdminDecoration {
  selected: boolean;
  faked: boolean;
}

function nodeBaseFields(node: MapNode, admin?: AdminDecoration) {
  const emphasis: NodeEmphasis = node.inferredRoot ? "inferred-root" : node.dimmed ? "dimmed" : "normal";
  const title = node.inferredRoot
    ? INFERRED_ROOT_TITLE
    : node.dimmed
      ? DIMMED_NODE_TITLE
      : node.unmanaged
        ? UNMANAGED_SWITCH_TITLE
        : undefined;
  const visual = nodeVisual(node.deviceType, node.state, emphasis);
  if (!admin || (!admin.selected && !admin.faked)) {
    return { id: node.id, label: node.label, title, ...visual };
  }
  // Admin-only decoration. Never mutate the cached visual: spread it. Selection is never
  // colour-only, so it also gets a checkmark glyph in the label (UI-SPEC Accessibility).
  const label = `${admin.selected ? "\u2713 " : ""}${node.label}${admin.faked ? "\nFAKED" : ""}`;
  if (!admin.selected) {
    return { id: node.id, label, title, ...visual };
  }
  return {
    id: node.id,
    label,
    title,
    ...visual,
    borderWidth: 3,
    color: {
      ...visual.color,
      border: SELECTED_BORDER_HEX,
      hover: { ...visual.color.hover, border: SELECTED_BORDER_HEX },
    },
  };
}

export function TopologyMap({
  topologyDevices,
  statuses,
  nowMs,
  editMode = false,
  onEditSaved,
  onEditFailed,
  incidentLookup,
  tierLookup,
  onSelectHost,
}: TopologyMapProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const edgesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const networkRef = useRef<Network | null>(null);
  const editModeRef = useRef(editMode);
  const adminMode = isAdminMode();
  const adminModeRef = useRef(adminMode);
  const adminSelected = useAdminStore((s) => s.selected);
  const adminFaked = useAdminStore((s) => s.faked);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // The manipulation callbacks below are only re-registered with vis-network when editMode
  // toggles (see the gating effect), so onEditSaved/onEditFailed/onSelectHost are read through
  // refs rather than captured directly -- otherwise a prop change between toggles would go
  // unseen. The click handler (registered once, see the mount effect) reads the current search
  // string the same way, so hostHref/incidentHref always build on top of whatever ?host=/
  // ?incident= is present at click time, not whatever it was when the handler was registered.
  const onEditSavedRef = useRef(onEditSaved);
  const onEditFailedRef = useRef(onEditFailed);
  const onSelectHostRef = useRef(onSelectHost);
  const searchRef = useRef(location.search);
  useEffect(() => {
    onEditSavedRef.current = onEditSaved;
  }, [onEditSaved]);
  useEffect(() => {
    onEditFailedRef.current = onEditFailed;
  }, [onEditFailed]);
  useEffect(() => {
    onSelectHostRef.current = onSelectHost;
  }, [onSelectHost]);
  useEffect(() => {
    searchRef.current = location.search;
  }, [location.search]);

  // Pending-edit overlay: a host-attribute write only becomes visible to other viewers once
  // changes are activated and the poller's next Livestatus poll picks it up -- without this
  // overlay, a just-drawn edge, a moved node, or a newly added switch would vanish from the map
  // the instant the next unrelated topology message re-syncs the DataSets.
  const pendingEdgeAdds = useRef(new Map<string, MapEdge>());
  const pendingEdgeRemovals = useRef(new Set<string>());
  const pendingNodeAdds = useRef(new Map<string, MapNode>());

  const model = useMemo(
    () => buildMapModel(topologyDevices, statuses, nowMs, incidentLookup),
    [topologyDevices, statuses, nowMs, incidentLookup],
  );
  const hasNodes = model.nodes.length > 0;

  // The click handler below is registered once, in the mount effect -- it reads the latest
  // model through this ref (rather than closing over `model` directly) so a consequence node's
  // incidentId/incidentRole is always current, exactly like editModeRef does for editMode.
  // The afterDrawing handler (registered once) reads the latest tier lookup through this ref;
  // a change redraws the canvas so the markers appear without waiting for a node update.
  const tierLookupRef = useRef<TierLookup>(tierLookup ?? {});
  useEffect(() => {
    tierLookupRef.current = tierLookup ?? {};
    networkRef.current?.redraw();
  }, [tierLookup]);

  const modelRef = useRef(model);
  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  // vis-network's built-in manipulation toolbar calls these with the shape documented at
  // https://visjs.github.io/vis-network/docs/network/manipulation.html; every write goes
  // through the shared REST writer's serialized GET-ETag-PUT flow, and none of them ever
  // activate the change -- activation is a separate, explicitly triggered batch action.
  async function addEdge(
    data: { from: string; to: string },
    callback: (result: { from: string; to: string; id: string } | null) => void,
  ) {
    const { from, to } = data;
    const edgeId = `${from}->${to}`;
    if (from === to || edgesRef.current?.get(edgeId)) {
      callback(null);
      return;
    }
    try {
      await updateParents(to, (parents) => [...parents, from]);
      pendingEdgeAdds.current.set(edgeId, { id: edgeId, from, to });
      pendingEdgeRemovals.current.delete(edgeId);
      callback({ ...data, id: edgeId });
      onEditSavedRef.current?.();
    } catch {
      callback(null);
      onEditFailedRef.current?.(CONNECTION_FAILURE);
    }
  }

  // `data.from`/`data.to` are the NEW endpoints; `data.id` is the edge being edited. vis-network
  // ignores a null callback result for editEdge (it just re-draws the untouched edge), so the
  // DataSet is patched by hand here and the id change is never handed back to vis-network.
  async function editEdge(data: { id: string; from: string; to: string }, callback: (result: null) => void) {
    const oldEdge = edgesRef.current?.get(data.id) as unknown as { from: string; to: string } | null;
    if (!oldEdge || (oldEdge.from === data.from && oldEdge.to === data.to)) {
      callback(null);
      return;
    }
    try {
      if (oldEdge.to === data.to) {
        await updateParents(data.to, (parents) => parents.filter((p) => p !== oldEdge.from).concat(data.from));
      } else {
        await updateParents(oldEdge.to, (parents) => parents.filter((p) => p !== oldEdge.from));
        await updateParents(data.to, (parents) => [...parents, data.from]);
      }
      const newId = `${data.from}->${data.to}`;
      edgesRef.current?.remove(data.id);
      edgesRef.current?.add({ id: newId, from: data.from, to: data.to });
      pendingEdgeAdds.current.delete(data.id);
      pendingEdgeRemovals.current.add(data.id);
      pendingEdgeAdds.current.set(newId, { id: newId, from: data.from, to: data.to });
      pendingEdgeRemovals.current.delete(newId);
      callback(null);
      onEditSavedRef.current?.();
    } catch {
      callback(null);
      onEditFailedRef.current?.(CONNECTION_FAILURE);
    }
  }

  async function deleteEdge(
    data: { nodes: string[]; edges: string[] },
    callback: (result: { nodes: string[]; edges: string[] } | null) => void,
  ) {
    const edgeIds = data.edges ?? [];
    if (edgeIds.length === 0) {
      callback(null);
      return;
    }
    for (const edgeId of edgeIds) {
      const edge = edgesRef.current?.get(edgeId) as unknown as { from: string; to: string } | null;
      if (!edge) {
        continue;
      }
      const parentLabel = (nodesRef.current?.get(edge.from) as { label?: string } | null)?.label ?? edge.from;
      const childLabel = (nodesRef.current?.get(edge.to) as { label?: string } | null)?.label ?? edge.to;
      const confirmed = window.confirm(
        `Remove this connection?\n\nThis removes the parent/child link between ${parentLabel} and ${childLabel}. It won't take effect until you press Apply changes.`,
      );
      if (!confirmed) {
        callback(null);
        return;
      }
    }
    try {
      for (const edgeId of edgeIds) {
        const edge = edgesRef.current?.get(edgeId) as unknown as { from: string; to: string } | null;
        if (!edge) {
          continue;
        }
        await updateParents(edge.to, (parents) => parents.filter((p) => p !== edge.from));
        pendingEdgeRemovals.current.add(edgeId);
        pendingEdgeAdds.current.delete(edgeId);
      }
      callback(data);
      onEditSavedRef.current?.();
    } catch {
      callback(null);
      onEditFailedRef.current?.(CONNECTION_FAILURE);
    }
  }

  // Adds a real, check-free Checkmk host for an unmanaged switch, styled with a "not yet
  // monitored" (PEND) visual until Activate Changes and the next poll pick it up. Node deletion
  // is never offered (deleteNode stays false below) -- a mistakenly added switch is removed in
  // Checkmk's own UI instead.
  async function addNode(
    data: { id: string; x: number; y: number; label: string },
    callback: (result: Record<string, unknown> | null) => void,
  ) {
    const name = window.prompt(ADD_NODE_PROMPT);
    if (!name) {
      callback(null);
      return;
    }
    if (!isValidHostName(name)) {
      callback(null);
      onEditFailedRef.current?.(INVALID_SWITCH_NAME_FAILURE);
      return;
    }
    if (nodesRef.current?.get(name)) {
      callback(null);
      onEditFailedRef.current?.(DUPLICATE_SWITCH_NAME_FAILURE);
      return;
    }
    const x = Math.round(data.x);
    const y = Math.round(data.y);
    try {
      await createUnmanagedSwitch(name, { x, y });
      pendingNodeAdds.current.set(name, {
        id: name,
        label: name,
        deviceType: "NetworkDevice",
        state: "PEND",
        position: { x, y },
        unmanaged: true,
        dimmed: false,
        incidentId: null,
        incidentRole: null,
        inferredRoot: false,
      });
      callback({
        ...data,
        id: name,
        label: name,
        title: UNMANAGED_SWITCH_TITLE,
        physics: false,
        x,
        y,
        ...nodeVisual("NetworkDevice", "PEND"),
      });
      onEditSavedRef.current?.();
    } catch {
      callback(null);
      onEditFailedRef.current?.(SWITCH_CREATE_FAILURE);
    }
  }

  // Construct once the container div actually exists -- vis-network's Network is not a React
  // component; it owns its own canvas and is only ever constructed here, never re-constructed on
  // a prop change (13-RESEARCH.md Pattern 1). No canvas div is rendered (see JSX below) until at
  // least one device exists, so on a fresh page load -- before the first MQTT topology message
  // arrives -- hasNodes starts false and containerRef.current is null. [hasNodes] (rather than an
  // empty dep array) makes this effect re-run the moment hasNodes flips to true and the div
  // commits, so the canvas still mounts on that first real data arrival instead of staying
  // permanently unconstructed until some unrelated remount (bug: devices loaded after initial
  // render never showed a map, only the "no connections" banner, until the page was reloaded or
  // re-navigated).
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const nodes = new DataSet<Record<string, unknown>>([]);
    const edges = new DataSet<Record<string, unknown>>([]);
    const network = new Network(container, { nodes, edges }, NETWORK_OPTIONS);

    network.once("stabilizationIterationsDone", () => {
      network.setOptions({ physics: false });
    });

    // D-01: registered unconditionally (not gated on editMode) so the grid is always visible,
    // in both read-only and edit mode.
    network.on("beforeDrawing", (ctx: CanvasRenderingContext2D) => drawGrid(ctx, network, container));

    network.on("afterDrawing", (ctx: CanvasRenderingContext2D) =>
      drawTierMarkers(ctx, network, container, tierLookupRef.current),
    );

    network.on("click", (params: {
      nodes: string[];
      edges?: string[];
      event?: { srcEvent?: { ctrlKey?: boolean; metaKey?: boolean } };
    }) => {
      const nodeId = params.nodes[0];
      // Admin selection: a plain click selects exactly that host, ctrl/cmd+click toggles it in
      // the multi-selection, and nothing navigates or opens host details in admin mode. A plain
      // click on empty canvas (not on a node or an edge) clears the selection (2026-10-02 user
      // request); ctrl/cmd+click on empty canvas does nothing so a slightly-off multi-select click
      // does not drop the selection. An edge click changes nothing.
      // vis-network `interaction.multiselect` is deliberately NOT enabled because it would also
      // change plain-click selection behavior. The modifier keys are read from
      // params.event.srcEvent.
      if (adminModeRef.current) {
        if (nodeId) {
          if (params.event?.srcEvent?.ctrlKey || params.event?.srcEvent?.metaKey) {
            useAdminStore.getState().toggleSelected(nodeId);
          } else {
            useAdminStore.getState().replaceSelection([nodeId]);
          }
        } else if (
          !params.edges?.length &&
          !params.event?.srcEvent?.ctrlKey &&
          !params.event?.srcEvent?.metaKey
        ) {
          useAdminStore.getState().clearSelection();
        }
        return;
      }
      if (editModeRef.current) {
        if (nodeId) {
          onSelectHostRef.current?.(nodeId);
        }
        return;
      }
      if (!nodeId) {
        // A click on empty canvas (not on a node or an edge) deselects the host: it closes the
        // details pane and returns the event history to every host (260928 follow-up).
        if (!params.edges?.length && new URLSearchParams(searchRef.current).has("host")) {
          navigate(withSearchParam(searchRef.current, "host", null));
        }
        return;
      }
      const node = modelRef.current.nodes.find((n) => n.id === nodeId);
      if (node?.incidentRole === "consequence" && node.incidentId) {
        navigate(incidentHref(searchRef.current, node.incidentId));
        return;
      }
      navigate(hostHref(searchRef.current, nodeId));
    });

    // Position persistence: a drag only ever writes while edit mode is on. The dropped position
    // is snapped to the grid before the write, so saved map_position labels are always on-grid;
    // a node placed from an existing off-grid saved label is left alone until it is next dragged
    // (D-02 -- no migration, no snapping on load/sync). A successful write freezes that node's
    // physics so later syncs never move it again.
    network.on("dragEnd", (params: { nodes: string[] }) => {
      if (!editModeRef.current) {
        return;
      }
      const positions = network.getPositions(params.nodes);
      for (const id of params.nodes) {
        const pos = positions[id];
        if (!pos) {
          continue;
        }
        const x = snapToGrid(pos.x);
        const y = snapToGrid(pos.y);
        nodesRef.current?.update({ id, x, y });
        setMapPosition(id, x, y)
          .then(() => {
            nodesRef.current?.update({ id, physics: false });
            onEditSavedRef.current?.();
          })
          .catch(() => {
            onEditFailedRef.current?.(POSITION_FAILURE);
          });
      }
    });

    nodesRef.current = nodes;
    edgesRef.current = edges;
    networkRef.current = network;

    return () => {
      network.destroy();
      nodesRef.current = null;
      edgesRef.current = null;
      networkRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: [hasNodes] is a
    // trigger dependency (not referenced in the body) so this re-runs exactly when the container
    // div commits; navigate/setMapPosition are stable module-level/hook values (see comment above).
  }, [hasNodes]);

  // Gating: manipulation and node dragging are only active while editMode is true. editNode is
  // never passed, so vis-network's toolbar never shows an "Edit Node" button; deleteNode stays
  // false (node deletion is never offered from the dashboard -- a mistakenly
  // added switch is removed in Checkmk's own UI instead). Runs after the mount effect above
  // (declaration order determines effect order), so networkRef.current is already set on the
  // very first render regardless of what editMode starts as.
  useEffect(() => {
    editModeRef.current = editMode;
    const network = networkRef.current;
    if (!network) {
      return;
    }
    network.setOptions({
      manipulation: {
        enabled: editMode,
        initiallyActive: editMode,
        addEdge,
        editEdge,
        deleteEdge,
        addNode,
        deleteNode: false,
      },
      interaction: { dragNodes: editMode, hover: true },
    });
    if (!editMode) {
      network.disableEditMode();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- addEdge/editEdge/deleteEdge/addNode
    // close over stable refs (nodesRef/edgesRef/onEditSavedRef/onEditFailedRef/the pending-edit
    // maps), so re-running this effect only on [editMode] is intentional: the callbacks always
    // read the latest values through those refs at call time, not through their own closure.
  }, [editMode]);

  // Sync -- diffs the current model (plus the pending-edit overlay above) against the live
  // DataSets and patches in place (nodes.update/add/remove, edges.add/remove); the
  // whole-graph-replacement method is never used here.
  useEffect(() => {
    const nodes = nodesRef.current;
    const edges = edgesRef.current;
    if (!nodes || !edges) {
      return;
    }

    // Prune overlay entries once the live model catches up to a locally-made edit: an add is no
    // longer needed once the model already contains it; a removal is no longer needed once the
    // model no longer contains it.
    const modelEdgeIds = new Set(model.edges.map((e) => e.id));
    for (const id of pendingEdgeAdds.current.keys()) {
      if (modelEdgeIds.has(id)) {
        pendingEdgeAdds.current.delete(id);
      }
    }
    for (const id of pendingEdgeRemovals.current) {
      if (!modelEdgeIds.has(id)) {
        pendingEdgeRemovals.current.delete(id);
      }
    }
    const modelNodeIds = new Set(model.nodes.map((n) => n.id));
    for (const id of pendingNodeAdds.current.keys()) {
      if (modelNodeIds.has(id)) {
        pendingNodeAdds.current.delete(id);
      }
    }

    const effectiveNodes = [
      ...model.nodes,
      ...Array.from(pendingNodeAdds.current.values()).filter((n) => !modelNodeIds.has(n.id)),
    ];
    const effectiveEdges = [
      ...model.edges.filter((e) => !pendingEdgeRemovals.current.has(e.id)),
      ...Array.from(pendingEdgeAdds.current.values()).filter((e) => !modelEdgeIds.has(e.id)),
    ];

    const positioned = withGridPositions(effectiveNodes);
    const existingNodeIds = new Set(nodes.getIds() as string[]);
    const effectiveNodeIds = new Set(positioned.map((n) => n.id));

    for (const node of positioned) {
      const admin = adminMode
        ? { selected: adminSelected.has(node.id), faked: node.id in adminFaked }
        : undefined;
      if (existingNodeIds.has(node.id)) {
        nodes.update(nodeBaseFields(node, admin));
      } else {
        nodes.add({
          ...nodeBaseFields(node, admin),
          x: node.x,
          y: node.y,
          ...(node.saved ? { physics: false } : {}),
        });
      }
    }
    for (const id of existingNodeIds) {
      if (!effectiveNodeIds.has(id)) {
        nodes.remove(id);
      }
    }

    const existingEdgeIds = new Set(edges.getIds() as string[]);
    const effectiveEdgeIds = new Set(effectiveEdges.map((e) => e.id));

    for (const edge of effectiveEdges) {
      if (existingEdgeIds.has(edge.id)) {
        edges.update({ id: edge.id, from: edge.from, to: edge.to });
      } else {
        edges.add({ id: edge.id, from: edge.from, to: edge.to });
      }
    }
    for (const id of existingEdgeIds) {
      if (!effectiveEdgeIds.has(id)) {
        edges.remove(id);
      }
    }
  }, [model, adminMode, adminSelected, adminFaked]);

  // Device-tree double-click -> centre the map on that host (non-admin overview). Requests that
  // were already pending when the map mounted are ignored (handledFocusSeq starts at the
  // current seq), so navigating back to the overview never re-centres on an old double-click.
  const focusRequest = useMapFocusStore((s) => s.request);
  const handledFocusSeq = useRef(useMapFocusStore.getState().request?.seq ?? 0);
  useEffect(() => {
    if (!focusRequest || focusRequest.seq === handledFocusSeq.current) {
      return;
    }
    handledFocusSeq.current = focusRequest.seq;
    const network = networkRef.current;
    if (!network || !nodesRef.current?.get(focusRequest.id)) {
      return;
    }
    network.focus(focusRequest.id, { scale: network.getScale(), animation: ZOOM_ANIMATION });
  }, [focusRequest]);

  const zoomBy = (factor: number) => {
    const network = networkRef.current;
    if (!network) {
      return;
    }
    const scale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, network.getScale() * factor));
    network.moveTo({ scale, animation: ZOOM_ANIMATION });
  };

  if (!hasNodes) {
    return (
      <div data-testid="topology-map" className={ROOT_CLASS_NAME}>
        <div className="max-w-md px-4 text-center">
          <h1 className="text-xl font-semibold">{EMPTY_STATE_HEADING}</h1>
          <p className="text-sm">{EMPTY_STATE_BODY}</p>
        </div>
      </div>
    );
  }

  // Includes a just-drawn, not-yet-applied-or-not-yet-polled-back pending edge -- model.edges
  // alone reflects only the last MQTT-sourced topology, which lags a real edit by up to one
  // Apply + one poll cycle. Without this, exiting edit mode right after drawing an edge
  // incorrectly flashed "No connections drawn yet" until the poller caught up (live UAT,
  // 2026-09-23), even though the edge was genuinely drawn and visibly on screen the whole time.
  const hasAnyEdges = model.edges.length > 0 || pendingEdgeAdds.current.size > 0;
  const showBanner = !hasAnyEdges && !editMode && !bannerDismissed;

  return (
    <div data-testid="topology-map" className={ROOT_CLASS_NAME}>
      {showBanner && (
        <div className="absolute left-2 right-2 top-2 z-10">
          <Banner status="info" message={NO_CONNECTIONS_BANNER_MESSAGE} onDismiss={() => setBannerDismissed(true)} />
        </div>
      )}
      {editMode && (
        <div className="pointer-events-none absolute bottom-2 left-2 z-10 rounded bg-bg-subtle px-2 py-1 text-xs text-fg-tertiary">
          {EDGE_DIRECTION_HINT}
        </div>
      )}
      <div
        className="absolute bottom-2 right-2 z-10 flex flex-col overflow-hidden rounded-sm border border-neutral-300 bg-bg-surface shadow-sm"
        role="group"
        aria-label="Map zoom"
      >
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(ZOOM_STEP)} className={ZOOM_BUTTON_CLASS}>
          <ZoomIcon kind="in" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          className={`${ZOOM_BUTTON_CLASS} border-t border-neutral-150`}
        >
          <ZoomIcon kind="out" />
        </button>
        <button
          type="button"
          aria-label="Fit to view"
          title="Fit to view"
          onClick={() => networkRef.current?.fit({ animation: ZOOM_ANIMATION })}
          className={`${ZOOM_BUTTON_CLASS} border-t border-neutral-150`}
        >
          <ZoomIcon kind="fit" />
        </button>
      </div>
      <div ref={containerRef} className="h-full w-full bg-white" />
    </div>
  );
}
