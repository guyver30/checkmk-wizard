// Renders useAppStore's `topology` slot as a live, read-only vis-network graph -- DASH-07.
// Mounts the vis-network Network exactly once (Phase 11 D-09: physics stabilizes then
// freezes) and merges every subsequent topology/status change into the existing node/edge
// DataSets via `.update()`/`.add()`/`.remove()` -- the whole-graph-replacement Network method
// is never called (13-RESEARCH.md Pattern 2 / Anti-Patterns). Edit mode (drag/connect via
// vis-network's manipulation toolbar) arrives in plans 13-06/13-07 -- this component only
// gates node-click navigation on the `editMode` prop so those plans' toolbar can reuse it
// without a rewrite.
//
// Takes its device list as a prop rather than reading the store directly, so a future
// tag-filter pass (Phase 15, D-11) can pass a pre-filtered list without changing this file.

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { DataSet } from "vis-data/peer";
import { Network } from "vis-network/peer";
import "vis-network/styles/vis-network.css";
import { Banner } from "kone-design-system";
import { nodeVisual } from "../lib/mapIcons";
import { buildMapModel, withGridPositions, type MapNode } from "../lib/topologyLayout";
import type { DevicePayload } from "../lib/types";

export interface TopologyMapProps {
  topologyDevices: unknown[];
  statuses: Record<string, DevicePayload>;
  nowMs: number;
  editMode?: boolean;
}

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

export function TopologyMap({ topologyDevices, statuses, nowMs, editMode = false }: TopologyMapProps) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const edgesRef = useRef<DataSet<Record<string, unknown>> | null>(null);
  const networkRef = useRef<Network | null>(null);
  const editModeRef = useRef(editMode);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    editModeRef.current = editMode;
  }, [editMode]);

  const model = useMemo(
    () => buildMapModel(topologyDevices, statuses, nowMs),
    [topologyDevices, statuses, nowMs],
  );
  const hasNodes = model.nodes.length > 0;

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

  // Sync -- diffs the current model against the live DataSets and patches in place
  // (nodes.update/add/remove, edges.add/remove); the whole-graph-replacement method is never
  // used here.
  useEffect(() => {
    const nodes = nodesRef.current;
    const edges = edgesRef.current;
    if (!nodes || !edges) {
      return;
    }

    const positioned = withGridPositions(model.nodes);
    const existingNodeIds = new Set(nodes.getIds() as string[]);
    const modelNodeIds = new Set(positioned.map((n) => n.id));

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
      if (!modelNodeIds.has(id)) {
        nodes.remove(id);
      }
    }

    const existingEdgeIds = new Set(edges.getIds() as string[]);
    const modelEdgeIds = new Set(model.edges.map((e) => e.id));

    for (const edge of model.edges) {
      if (existingEdgeIds.has(edge.id)) {
        edges.update({ id: edge.id, from: edge.from, to: edge.to });
      } else {
        edges.add({ id: edge.id, from: edge.from, to: edge.to });
      }
    }
    for (const id of existingEdgeIds) {
      if (!modelEdgeIds.has(id)) {
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
