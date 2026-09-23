import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TopologyMap } from "./TopologyMap";
import { instances, resetFakeNetworks } from "../test/fakeVisNetwork";
import type { DevicePayload } from "../lib/types";
import * as checkmkWrite from "../lib/checkmkWrite";

// 13-06: every write in edit mode goes through checkmkWrite.ts (13-05) -- mocked here so these
// tests exercise TopologyMap's own callback wiring (what it calls, with what args, and how it
// reacts to success/failure) without making a real network call. isValidHostName is kept real
// (a pure regex) since Task 2's addNode tests need actual validation behavior, not a stub.
vi.mock("../lib/checkmkWrite", () => ({
  updateParents: vi.fn(),
  setMapPosition: vi.fn(),
  createUnmanagedSwitch: vi.fn(),
  isValidHostName: (name: string) => /^[-0-9a-zA-Z_.]+$/.test(name),
}));

type ManipulationCallback<T> = (data: T, callback: (result: T | null) => void) => Promise<void>;

const NOW_MS = Date.parse("2026-09-23T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();

function device(overrides: Partial<DevicePayload> & { id: string }): DevicePayload {
  return { state: "OK", timestamp: FRESH_TIMESTAMP, device_type: "NetworkDevice", ...overrides };
}

// Probe route -- TopologyMap navigates imperatively (network.on("click", ...)), not via a
// React <Link>, so the only way to observe the navigation is to actually route to /details and
// read back the ?id= it was called with (same pattern DetailsRoute.test.tsx uses to assert on
// ?id=, just driven from the other end).
function DetailsProbe() {
  const [params] = useSearchParams();
  return <div data-testid="details-probe">{params.get("id") ?? ""}</div>;
}

function renderMap(props: Partial<React.ComponentProps<typeof TopologyMap>> = {}) {
  const defaultProps: React.ComponentProps<typeof TopologyMap> = {
    topologyDevices: [],
    statuses: {},
    nowMs: NOW_MS,
  };
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<TopologyMap {...defaultProps} {...props} />} />
        <Route path="/details" element={<DetailsProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

// Rerenders the same MemoryRouter/Routes tree renderMap() built, with new props -- used by the
// edit-mode tests below to simulate a new topology/statuses prop arriving (MQTT update) while
// the map stays mounted.
function rerenderMap(
  rerender: (ui: React.ReactElement) => void,
  props: Partial<React.ComponentProps<typeof TopologyMap>> = {},
) {
  const defaultProps: React.ComponentProps<typeof TopologyMap> = {
    topologyDevices: [],
    statuses: {},
    nowMs: NOW_MS,
  };
  rerender(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<TopologyMap {...defaultProps} {...props} />} />
        <Route path="/details" element={<DetailsProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resetFakeNetworks();
  vi.mocked(checkmkWrite.updateParents).mockReset();
  vi.mocked(checkmkWrite.setMapPosition).mockReset();
  vi.mocked(checkmkWrite.createUnmanagedSwitch).mockReset();
});

describe("TopologyMap", () => {
  it("has data-testid='topology-map' in the empty (zero-device) state", () => {
    renderMap();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("renders the empty-state heading and body, and constructs no Network, with zero devices", () => {
    renderMap();
    expect(screen.getByText("No connections drawn yet")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Every device is shown below, ready to connect. Turn on Edit topology and drag between two devices to draw a link — it saves to Checkmk once you Apply.",
      ),
    ).toBeInTheDocument();
    expect(instances).toHaveLength(0);
  });

  it("constructs the Network exactly once across rerenders with changed statuses, reusing the same node DataSet instance", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    const { rerender } = renderMap({ topologyDevices, statuses: { h1: device({ id: "h1", state: "OK" }) } });
    expect(instances).toHaveLength(1);
    const nodesDataSet = instances[0].data.nodes;

    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <TopologyMap
                topologyDevices={topologyDevices}
                statuses={{ h1: device({ id: "h1", state: "CRIT" }) }}
                nowMs={NOW_MS}
              />
            }
          />
          <Route path="/details" element={<DetailsProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(instances).toHaveLength(1);
    expect(instances[0].data.nodes).toBe(nodesDataSet);
  });

  it("updates an existing node's image in place when its status flips from OK to CRIT", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    const { rerender } = renderMap({ topologyDevices, statuses: { h1: device({ id: "h1", state: "OK" }) } });
    const nodes = instances[0].data.nodes as unknown as { get: (id: string) => { image: string } };
    const imageBefore = nodes.get("h1").image;

    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <TopologyMap
                topologyDevices={topologyDevices}
                statuses={{ h1: device({ id: "h1", state: "CRIT" }) }}
                nowMs={NOW_MS}
              />
            }
          />
          <Route path="/details" element={<DetailsProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const imageAfter = nodes.get("h1").image;
    expect(imageAfter).not.toBe(imageBefore);
  });

  it("removes a vanished device's node and edges, and adds a new device's node with x/y", () => {
    const topologyDevices = [
      { id: "h1", parents: [] },
      { id: "h2", parents: ["h1"] },
    ];
    const statuses = {
      h1: device({ id: "h1" }),
      h2: device({ id: "h2" }),
    };
    const { rerender } = renderMap({ topologyDevices, statuses });
    const network = instances[0];
    const nodesBefore = network.data.nodes as unknown as { getIds: () => string[] };
    const edgesBefore = network.data.edges as unknown as { getIds: () => string[] };
    expect(nodesBefore.getIds().sort()).toEqual(["h1", "h2"]);
    expect(edgesBefore.getIds()).toEqual(["h1->h2"]);

    const nextTopologyDevices = [
      { id: "h1", parents: [] },
      { id: "h3", parents: [] },
    ];
    const nextStatuses = { h1: device({ id: "h1" }), h3: device({ id: "h3" }) };
    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={<TopologyMap topologyDevices={nextTopologyDevices} statuses={nextStatuses} nowMs={NOW_MS} />}
          />
          <Route path="/details" element={<DetailsProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const nodesAfter = network.data.nodes as unknown as { getIds: () => string[]; get: (id: string) => { x: number; y: number } };
    const edgesAfter = network.data.edges as unknown as { getIds: () => string[] };
    expect(nodesAfter.getIds().sort()).toEqual(["h1", "h3"]);
    expect(edgesAfter.getIds()).toEqual([]);
    expect(typeof nodesAfter.get("h3").x).toBe("number");
    expect(typeof nodesAfter.get("h3").y).toBe("number");
  });

  it("creates edges for every parent->child pair, with arrows pointing 'to'", () => {
    const topologyDevices = [
      { id: "parent1", parents: [] },
      { id: "child1", parents: ["parent1"] },
    ];
    const statuses = { parent1: device({ id: "parent1" }), child1: device({ id: "child1" }) };
    renderMap({ topologyDevices, statuses });
    const edges = instances[0].data.edges as unknown as { get: (id: string) => { from: string; to: string } };
    expect(edges.get("parent1->child1")).toMatchObject({ from: "parent1", to: "child1" });
    expect(instances[0].options.edges).toMatchObject({ arrows: "to" });
  });

  it("adds a node with a saved map_position at its exact x/y with physics false", () => {
    const topologyDevices = [{ id: "h1", parents: [], map_position: "300,40" }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) } });
    const nodes = instances[0].data.nodes as unknown as {
      get: (id: string) => { x: number; y: number; physics?: boolean };
    };
    const item = nodes.get("h1");
    expect(item.x).toBe(300);
    expect(item.y).toBe(40);
    expect(item.physics).toBe(false);
  });

  it("gives an unsaved node its withGridPositions coordinates without a physics key", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) } });
    const nodes = instances[0].data.nodes as unknown as {
      get: (id: string) => { x: number; y: number; physics?: boolean };
    };
    const item = nodes.get("h1");
    expect(item.x).toBe(0);
    expect(item.y).toBe(0);
    expect(item.physics).toBeUndefined();
  });

  it("calls setOptions with physics false when the fake emits stabilizationIterationsDone", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) } });
    act(() => {
      instances[0].emit("stabilizationIterationsDone");
    });
    expect(instances[0].setOptionsCalls).toContainEqual({ physics: false });
  });

  it("navigates to /details?id=h1 on a node click when not in edit mode", async () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: false });
    act(() => {
      instances[0].emit("click", { nodes: ["h1"] });
    });
    expect(await screen.findByTestId("details-probe")).toHaveTextContent("h1");
  });

  it("does not navigate on a node click while in edit mode", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: true });
    act(() => {
      instances[0].emit("click", { nodes: ["h1"] });
    });
    expect(screen.queryByTestId("details-probe")).not.toBeInTheDocument();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("shows the no-connections banner with devices present, zero edges, and edit mode off, and dismisses it", () => {
    const topologyDevices = [
      { id: "h1", parents: [] },
      { id: "h2", parents: [] },
    ];
    const statuses = { h1: device({ id: "h1" }), h2: device({ id: "h2" }) };
    renderMap({ topologyDevices, statuses, editMode: false });
    const message = screen.getByText("No connections drawn yet — turn on Edit topology to start.");
    expect(message).toBeInTheDocument();

    const dismissButton = screen.getByRole("button", { name: /dismiss/i });
    act(() => {
      dismissButton.click();
    });
    expect(screen.queryByText("No connections drawn yet — turn on Edit topology to start.")).not.toBeInTheDocument();
  });

  it("does not show the no-connections banner when edit mode is on", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: true });
    expect(screen.queryByText("No connections drawn yet — turn on Edit topology to start.")).not.toBeInTheDocument();
  });

  it("gives an unmanaged node's DataSet item the unmanaged-switch title", () => {
    const topologyDevices = [{ id: "sw1", parents: [], unmanaged: true }];
    renderMap({ topologyDevices, statuses: {} });
    const nodes = instances[0].data.nodes as unknown as { get: (id: string) => { title?: string } };
    expect(nodes.get("sw1").title).toBe("Unmanaged switch (not monitored)");
  });

  it("has data-testid='topology-map' when nodes are present", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) } });
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });
});

describe("TopologyMap edit mode (13-06)", () => {
  it("enables manipulation/dragNodes and passes addEdge/editEdge/deleteEdge/addNode (never editNode) when editMode turns on, then disables and calls disableEditMode when it turns off", () => {
    const topologyDevices = [{ id: "h1", parents: [] }];
    const statuses = { h1: device({ id: "h1" }) };
    const { rerender } = renderMap({ topologyDevices, statuses, editMode: false });
    const network = instances[0];

    rerenderMap(rerender, { topologyDevices, statuses, editMode: true });

    const onCall = network.setOptionsCalls[network.setOptionsCalls.length - 1];
    expect(onCall).toMatchObject({
      manipulation: expect.objectContaining({ enabled: true, initiallyActive: true, deleteNode: false }),
      interaction: expect.objectContaining({ dragNodes: true }),
    });
    const manipulation = (onCall as { manipulation: Record<string, unknown> }).manipulation;
    expect(typeof manipulation.addEdge).toBe("function");
    expect(typeof manipulation.editEdge).toBe("function");
    expect(typeof manipulation.deleteEdge).toBe("function");
    expect(typeof manipulation.addNode).toBe("function");
    expect(manipulation.editNode).toBeUndefined();

    rerenderMap(rerender, { topologyDevices, statuses, editMode: false });
    const offCall = network.setOptionsCalls[network.setOptionsCalls.length - 1];
    expect(offCall).toMatchObject({
      manipulation: expect.objectContaining({ enabled: false }),
      interaction: expect.objectContaining({ dragNodes: false }),
    });
    expect(network.disableEditModeCallCount).toBe(1);
  });

  it("addEdge writes updateParents(to, add-from) and adds the edge with onEditSaved", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const onEditSaved = vi.fn();
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: [] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true, onEditSaved });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const addEdge = manipulation.addEdge as ManipulationCallback<{ from: string; to: string; id?: string }>;
    const callback = vi.fn();

    await act(async () => {
      await addEdge({ from: "sw", to: "h1" }, callback);
    });

    expect(mockUpdateParents).toHaveBeenCalledWith("h1", expect.any(Function));
    expect(mockUpdateParents.mock.calls[0][1]([])).toEqual(["sw"]);
    expect(callback).toHaveBeenCalledWith(expect.objectContaining({ id: "sw->h1", from: "sw", to: "h1" }));
    expect(onEditSaved).toHaveBeenCalledTimes(1);
  });

  it("addEdge rejects self-loops and duplicate edges without writing", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const addEdge = manipulation.addEdge as ManipulationCallback<{ from: string; to: string }>;

    const selfLoopCallback = vi.fn();
    await act(async () => {
      await addEdge({ from: "h1", to: "h1" }, selfLoopCallback);
    });
    expect(selfLoopCallback).toHaveBeenCalledWith(null);

    const dupCallback = vi.fn();
    await act(async () => {
      await addEdge({ from: "sw", to: "h1" }, dupCallback);
    });
    expect(dupCallback).toHaveBeenCalledWith(null);

    expect(mockUpdateParents).not.toHaveBeenCalled();
  });

  it("addEdge failure calls callback(null) and onEditFailed with the connection copy, without onEditSaved", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockRejectedValue(new Error("rejected"));
    const onEditSaved = vi.fn();
    const onEditFailed = vi.fn();
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: [] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true, onEditSaved, onEditFailed });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const addEdge = manipulation.addEdge as ManipulationCallback<{ from: string; to: string }>;
    const callback = vi.fn();

    await act(async () => {
      await addEdge({ from: "sw", to: "h1" }, callback);
    });

    expect(callback).toHaveBeenCalledWith(null);
    expect(onEditFailed).toHaveBeenCalledWith({
      title: "Couldn't save that connection",
      body: "Checkmk rejected the update. Check that both devices still exist, then try again.",
    });
    expect(onEditSaved).not.toHaveBeenCalled();
  });

  it("editEdge to the same child makes one updateParents call and swaps the edge id in the DataSet", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const onEditSaved = vi.fn();
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "sw2", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    const statuses = { sw: device({ id: "sw" }), sw2: device({ id: "sw2" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true, onEditSaved });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const editEdge = manipulation.editEdge as ManipulationCallback<{ id: string; from: string; to: string }>;
    const callback = vi.fn();

    await act(async () => {
      await editEdge({ id: "sw->h1", from: "sw2", to: "h1" }, callback);
    });

    expect(mockUpdateParents).toHaveBeenCalledTimes(1);
    expect(mockUpdateParents).toHaveBeenCalledWith("h1", expect.any(Function));
    expect(mockUpdateParents.mock.calls[0][1](["sw"])).toEqual(["sw2"]);
    expect(callback).toHaveBeenCalledWith(null);
    expect(onEditSaved).toHaveBeenCalledTimes(1);

    const edges = instances[0].data.edges as unknown as { getIds: () => string[] };
    expect(edges.getIds()).toContain("sw2->h1");
    expect(edges.getIds()).not.toContain("sw->h1");
  });

  it("editEdge to a different child makes two updateParents calls (remove old, add new)", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
      { id: "h2", parents: [] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }), h2: device({ id: "h2" }) };
    renderMap({ topologyDevices, statuses, editMode: true });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const editEdge = manipulation.editEdge as ManipulationCallback<{ id: string; from: string; to: string }>;
    const callback = vi.fn();

    await act(async () => {
      await editEdge({ id: "sw->h1", from: "sw", to: "h2" }, callback);
    });

    expect(mockUpdateParents).toHaveBeenCalledTimes(2);
    expect(mockUpdateParents).toHaveBeenNthCalledWith(1, "h1", expect.any(Function));
    expect(mockUpdateParents.mock.calls[0][1](["sw"])).toEqual([]);
    expect(mockUpdateParents).toHaveBeenNthCalledWith(2, "h2", expect.any(Function));
    expect(mockUpdateParents.mock.calls[1][1]([])).toEqual(["sw"]);
    expect(callback).toHaveBeenCalledWith(null);
  });

  it("deleteEdge cancelled by window.confirm makes no write and calls callback(null)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const deleteEdge = manipulation.deleteEdge as ManipulationCallback<{ nodes: string[]; edges: string[] }>;
    const callback = vi.fn();

    await act(async () => {
      await deleteEdge({ nodes: [], edges: ["sw->h1"] }, callback);
    });

    expect(callback).toHaveBeenCalledWith(null);
    expect(mockUpdateParents).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("deleteEdge confirmed removes the parent, calls callback(data) and onEditSaved, and the confirm text names both devices", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const onEditSaved = vi.fn();
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    renderMap({ topologyDevices, statuses, editMode: true, onEditSaved });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const deleteEdge = manipulation.deleteEdge as ManipulationCallback<{ nodes: string[]; edges: string[] }>;
    const callback = vi.fn();
    const data = { nodes: [], edges: ["sw->h1"] };

    await act(async () => {
      await deleteEdge(data, callback);
    });

    expect(confirmSpy).toHaveBeenCalled();
    const confirmText = confirmSpy.mock.calls[0][0] as string;
    expect(confirmText).toContain("Remove this connection?");
    expect(confirmText).toContain("sw");
    expect(confirmText).toContain("h1");
    expect(mockUpdateParents).toHaveBeenCalledWith("h1", expect.any(Function));
    expect(mockUpdateParents.mock.calls[0][1](["sw"])).toEqual([]);
    expect(callback).toHaveBeenCalledWith(data);
    expect(onEditSaved).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  it("dragEnd in edit mode saves the dragged node's position via setMapPosition and calls onEditSaved", async () => {
    const mockSetMapPosition = vi.mocked(checkmkWrite.setMapPosition);
    mockSetMapPosition.mockResolvedValue(undefined);
    const onEditSaved = vi.fn();
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: true, onEditSaved });
    const network = instances[0];
    const nodes = network.data.nodes as unknown as { update: (item: Record<string, unknown>) => void };
    nodes.update({ id: "h1", x: 77, y: -33 });

    act(() => {
      network.emit("dragEnd", { nodes: ["h1"] });
    });

    await waitFor(() => expect(mockSetMapPosition).toHaveBeenCalledWith("h1", 77, -33));
    await waitFor(() => expect(onEditSaved).toHaveBeenCalledTimes(1));
  });

  it("dragEnd in read-only mode makes no write", () => {
    const mockSetMapPosition = vi.mocked(checkmkWrite.setMapPosition);
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: false });
    const network = instances[0];

    act(() => {
      network.emit("dragEnd", { nodes: ["h1"] });
    });

    expect(mockSetMapPosition).not.toHaveBeenCalled();
  });

  it("dragEnd failure calls onEditFailed with the position copy", async () => {
    const mockSetMapPosition = vi.mocked(checkmkWrite.setMapPosition);
    mockSetMapPosition.mockRejectedValue(new Error("rejected"));
    const onEditFailed = vi.fn();
    const topologyDevices = [{ id: "h1", parents: [] }];
    renderMap({ topologyDevices, statuses: { h1: device({ id: "h1" }) }, editMode: true, onEditFailed });
    const network = instances[0];

    act(() => {
      network.emit("dragEnd", { nodes: ["h1"] });
    });

    await waitFor(() =>
      expect(onEditFailed).toHaveBeenCalledWith({
        title: "Couldn't save that position",
        body: "Checkmk rejected the update. Check that the device still exists, then try again.",
      }),
    );
  });

  it("keeps a locally-added edge visible until the live topology catches up, then drops the overlay once it does", async () => {
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: [] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    const { rerender } = renderMap({ topologyDevices, statuses, editMode: true });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const addEdge = manipulation.addEdge as ManipulationCallback<{ from: string; to: string }>;

    await act(async () => {
      await addEdge({ from: "sw", to: "h1" }, vi.fn());
    });

    const edges = instances[0].data.edges as unknown as { getIds: () => string[] };
    expect(edges.getIds()).toContain("sw->h1");

    // Topology re-arrives, but the poller hasn't caught up yet -- h1 still shows no parents.
    rerenderMap(rerender, { topologyDevices, statuses, editMode: true });
    expect(edges.getIds()).toContain("sw->h1");

    // Live topology now reflects the edge -- overlay entry is pruned, edge stays model-driven.
    const caughtUpTopologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    rerenderMap(rerender, { topologyDevices: caughtUpTopologyDevices, statuses, editMode: true });
    expect(edges.getIds()).toContain("sw->h1");

    // A later topology that drops the edge again is now honored (no longer held by the overlay).
    rerenderMap(rerender, { topologyDevices, statuses, editMode: true });
    expect(edges.getIds()).not.toContain("sw->h1");
  });

  it("keeps a locally-deleted edge absent until the live topology also drops it", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const mockUpdateParents = vi.mocked(checkmkWrite.updateParents);
    mockUpdateParents.mockResolvedValue(undefined);
    const topologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: ["sw"] },
    ];
    const statuses = { sw: device({ id: "sw" }), h1: device({ id: "h1" }) };
    const { rerender } = renderMap({ topologyDevices, statuses, editMode: true });
    const manipulation = instances[0].lastManipulation() as Record<string, unknown>;
    const deleteEdge = manipulation.deleteEdge as ManipulationCallback<{ nodes: string[]; edges: string[] }>;

    await act(async () => {
      await deleteEdge({ nodes: [], edges: ["sw->h1"] }, vi.fn());
    });

    const edges = instances[0].data.edges as unknown as { getIds: () => string[] };
    expect(edges.getIds()).not.toContain("sw->h1");

    // Topology still shows the stale parent -- overlay keeps the edge hidden.
    rerenderMap(rerender, { topologyDevices, statuses, editMode: true });
    expect(edges.getIds()).not.toContain("sw->h1");

    // Live topology now reflects the deletion -- overlay entry is pruned.
    const caughtUpTopologyDevices = [
      { id: "sw", parents: [] },
      { id: "h1", parents: [] },
    ];
    rerenderMap(rerender, { topologyDevices: caughtUpTopologyDevices, statuses, editMode: true });
    expect(edges.getIds()).not.toContain("sw->h1");

    confirmSpy.mockRestore();
  });
});
