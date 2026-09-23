// Renders useAppStore's `topology` slot as a live, editable vis-network graph. Mounts the
// vis-network Network exactly once (physics stabilizes then freezes on first load) and merges
// every subsequent topology/status change into the existing node/edge DataSets via
// `.update()`/`.add()`/`.remove()` -- the whole-graph-replacement Network method is never called.
//
// The `editMode` prop gates both node-click navigation and vis-network's built-in manipulation
// toolbar: off, a click navigates to /details and dragging/drawing is disabled; on, the
// toolbar's addEdge/editEdge/deleteEdge/addNode callbacks write directly to Checkmk through the
// shared REST writer module and dragging a node persists its position. Every write applies
// immediately to Checkmk but is never activated from here -- activating changes is a separate,
// explicitly triggered batch action owned by the toolbar UI that surrounds this component.
//
// Takes its device list as a prop rather than reading the store directly, so a future
// tag-filter pass can narrow the input list without changing this file.

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { DataSet } from "vis-data/peer";
import { Network } from "vis-network/peer";
import "vis-network/styles/vis-network.css";
import { Banner } from "kone-design-system";
import { nodeVisual } from "../lib/mapIcons";
import { createUnmanagedSwitch, isValidHostName, setMapPosition, updateParents } from "../lib/checkmkWrite";
import { buildMapModel, withGridPositions, type MapEdge, type MapNode } from "../lib/topologyLayout";
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

const ROOT_CLASS_NAME =
  "relative flex h-full w-full items-center justify-center rounded-md border border-neutral-150 bg-bg-subtle";

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
function nodeBaseFields(node: MapNode) {
  return {
    id: node.id,
    label: node.label,
    title: node.unmanaged ? UNMANAGED_SWITCH_TITLE : undefined,
    ...nodeVisual(node.deviceType, node.state),
  };
}

export function TopologyMap({
  topologyDevices,
  statuses,
  nowMs,
  editMode = false,
  onEditSaved,
  onEditFailed,
}: TopologyMapProps) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const edgesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const networkRef = useRef<Network | null>(null);
  const editModeRef = useRef(editMode);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // The manipulation callbacks below are only re-registered with vis-network when editMode
  // toggles (see the gating effect), so onEditSaved/onEditFailed are read through refs rather
  // than captured directly -- otherwise a prop change between toggles would go unseen.
  const onEditSavedRef = useRef(onEditSaved);
  const onEditFailedRef = useRef(onEditFailed);
  useEffect(() => {
    onEditSavedRef.current = onEditSaved;
  }, [onEditSaved]);
  useEffect(() => {
    onEditFailedRef.current = onEditFailed;
  }, [onEditFailed]);

  // Pending-edit overlay: a host-attribute write only becomes visible to other viewers once
  // changes are activated and the poller's next Livestatus poll picks it up -- without this
  // overlay, a just-drawn edge, a moved node, or a newly added switch would vanish from the map
  // the instant the next unrelated topology message re-syncs the DataSets.
  const pendingEdgeAdds = useRef(new Map<string, MapEdge>());
  const pendingEdgeRemovals = useRef(new Set<string>());
  const pendingNodeAdds = useRef(new Map<string, MapNode>());

  const model = useMemo(
    () => buildMapModel(topologyDevices, statuses, nowMs),
    [topologyDevices, statuses, nowMs],
  );
  const hasNodes = model.nodes.length > 0;

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

  // Mount once -- vis-network's Network is not a React component; it owns its own canvas and
  // is only ever constructed here, never re-constructed on a prop change (13-RESEARCH.md
  // Pattern 1). No canvas div is rendered (see JSX below) until at least one device exists, so
  // this effect's containerRef guard also covers the "zero devices -> no Network" case.
  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const nodes = new DataSet<Record<string, unknown>>([]);
    const edges = new DataSet<Record<string, unknown>>([]);
    const network = new Network(containerRef.current, { nodes, edges }, NETWORK_OPTIONS);

    network.once("stabilizationIterationsDone", () => {
      network.setOptions({ physics: false });
    });

    network.on("click", (params: { nodes: string[] }) => {
      if (editModeRef.current) {
        return;
      }
      const nodeId = params.nodes[0];
      if (nodeId) {
        navigate(`/details?id=${encodeURIComponent(nodeId)}`);
      }
    });

    // Position persistence: a drag only ever writes while edit mode is on. A successful write
    // freezes that node's physics so later syncs never move it again.
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
        setMapPosition(id, pos.x, pos.y)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: mount once (see comment above).
  }, []);

  // Gating: manipulation and node dragging are only active while editMode is true. editNode is
  // never passed, so vis-network's toolbar never shows an "Edit Node" button; deleteNode stays
  // false (node deletion is never offered from the dashboard -- a mistakenly
  // added switch is removed in Checkmk's own UI instead). Runs after the mount effect above
  // (declaration order determines effect order), so networkRef.current is already set even on
  // the very first render when editMode starts out true.
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
      if (existingNodeIds.has(node.id)) {
        nodes.update(nodeBaseFields(node));
      } else {
        nodes.add({
          ...nodeBaseFields(node),
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
  }, [model]);

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

  const showBanner = model.edges.length === 0 && !editMode && !bannerDismissed;

  return (
    <div data-testid="topology-map" className={ROOT_CLASS_NAME}>
      {showBanner && (
        <div className="absolute left-2 right-2 top-2 z-10">
          <Banner status="info" message={NO_CONNECTIONS_BANNER_MESSAGE} onDismiss={() => setBannerDismissed(true)} />
        </div>
      )}
      <div ref={containerRef} className="h-full w-full bg-white" />
    </div>
  );
}
