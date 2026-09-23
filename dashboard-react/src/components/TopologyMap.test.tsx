import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { TopologyMap } from "./TopologyMap";
import { instances, resetFakeNetworks } from "../test/fakeVisNetwork";
import type { DevicePayload } from "../lib/types";

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

beforeEach(() => {
  resetFakeNetworks();
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
