import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndexRoute } from "./IndexRoute";
import * as checkmkWrite from "../lib/checkmkWrite";
import type { IncidentLookup } from "../lib/incidents";
import { __setAdminModeForTests } from "../lib/adminMode";
import { useAppStore } from "../store/useAppStore";

// Every write in edit mode goes through checkmkWrite.ts -- mocked here so these route-level
// tests exercise IndexRoute's own wiring (what it calls, how it reacts to success/failure)
// without making a real network call, the same convention TopologyMap.test.tsx already uses.
//
// probeEditingAvailable() (amended 2026-09-30, quick 260930-hpy) replaces the old
// isTopologyEditingConfigured() config.ts mock below -- resolved true by default in the
// top-level beforeEach so the Switch/toolbar tests don't also have to wait out the
// disabled-until-probed window; TopologyToolbar.test.tsx and the dedicated
// "editing unavailable" test further down already cover the disabled-hint state.
vi.mock("../lib/checkmkWrite", () => ({
  countPendingChanges: vi.fn(),
  activateChanges: vi.fn(),
  setCriticality: vi.fn(),
  probeEditingAvailable: vi.fn(),
}));

// TopologyMap itself is exercised by TopologyMap.test.tsx (including its real onEditSaved/
// onEditFailed call sites via vis-network's manipulation toolbar); here it's replaced with a
// stand-in exposing the same props IndexRoute wires, so these tests can trigger
// onEditSaved/onEditFailed directly without driving a real vis-network instance.
vi.mock("../components/TopologyMap", () => ({
  TopologyMap: (props: {
    editMode?: boolean;
    onEditSaved?: () => void;
    onEditFailed?: (failure: { title: string; body: string }) => void;
    incidentLookup?: IncidentLookup;
    onSelectHost?: (id: string) => void;
  }) => (
    <div
      data-testid="topology-map"
      data-edit-mode={String(props.editMode ?? false)}
      data-incident-lookup-size={String(props.incidentLookup?.size ?? 0)}
    >
      <button onClick={() => props.onEditSaved?.()}>trigger-saved</button>
      <button onClick={() => props.onEditFailed?.({ title: "Map failure", body: "Map failure body" })}>
        trigger-failed
      </button>
      <button onClick={() => props.onSelectHost?.("h1")}>trigger-select-h1</button>
    </div>
  ),
}));

// Same reset pattern as useAppStore.test.ts: a snapshot of the store's initial state, replaced
// wholesale between tests via the test-only `true` argument.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
  vi.mocked(checkmkWrite.probeEditingAvailable).mockReset().mockResolvedValue(true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

function renderIndex() {
  return render(
    <MemoryRouter>
      <IndexRoute />
    </MemoryRouter>,
  );
}

function renderIndexAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <IndexRoute />
    </MemoryRouter>,
  );
}

describe("IndexRoute", () => {
  it("no longer renders the fleet state summary on the dashboard (it lives in the header)", () => {
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("status", { name: /fleet state summary/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

});

describe("IndexRoute admin mode", () => {
  afterEach(() => {
    __setAdminModeForTests(false);
  });

  it("renders no admin chrome without admin mode", () => {
    renderIndex();
    expect(screen.queryByText(/ADMIN MODE/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set DOWN" })).not.toBeInTheDocument();
  });

  it("renders the banner and action bar and disables the edit switch in admin mode", async () => {
    __setAdminModeForTests(true);
    renderIndex();
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("ADMIN MODE - no hosts faked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set DOWN" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Edit topology" })).toBeDisabled();
    expect(screen.getByText("Unavailable in admin mode")).toBeInTheDocument();
  });
});

describe("IndexRoute edit-topology toolbar, Apply flow, Snackbars and idle exit", () => {
  beforeEach(() => {
    vi.mocked(checkmkWrite.countPendingChanges).mockReset();
    vi.mocked(checkmkWrite.activateChanges).mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Flushes microtasks queued by an awaited mock Promise (countPendingChanges/activateChanges)
  // without letting real timers elapse -- fake timers intercept setTimeout, but Promise
  // microtasks still resolve on their own; this just gives React's effects a tick to apply the
  // resulting state update before the next assertion.
  async function flush() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  it("initial render: the switch is unchecked, and TopologyMap receives editMode false", () => {
    renderIndex();
    const toggle = screen.getByRole("switch", { name: "Edit topology" }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(screen.getByTestId("topology-map")).toHaveAttribute("data-edit-mode", "false");
  });

  it("when probeEditingAvailable resolves false, the switch stays disabled with the configuration hint, and CriticalityEditor never renders", async () => {
    vi.mocked(checkmkWrite.probeEditingAvailable).mockReset().mockResolvedValue(false);
    renderIndex();
    await flush();

    const toggle = screen.getByRole("switch", { name: "Edit topology" }) as HTMLInputElement;
    expect(toggle).toBeDisabled();
    expect(
      screen.getByText("Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Criticality & dependencies" })).not.toBeInTheDocument();
  });

  it("edit mode gives the map the full centre: no incident list, event history or details pane; tree stays", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValue(0);
    renderIndexAt("/?host=h1");
    await flush(); // let the mount-time editingAvailable probe resolve before toggling
    expect(screen.getByRole("log", { name: /recent events/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /collapse host details/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    expect(screen.queryByText("No open incidents")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /collapse incidents/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("log", { name: /recent events/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /collapse host details/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /collapse device tree/i })).toBeInTheDocument();
    expect(screen.getByTestId("topology-map")).toHaveAttribute("data-edit-mode", "true");

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();
    expect(screen.getByRole("log", { name: /recent events/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /collapse host details/i })).toBeInTheDocument();
  });

  it("turning the switch on calls countPendingChanges once and shows its result as the pending count", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(2);
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    expect(checkmkWrite.countPendingChanges).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("2 changes not yet applied");
  });

  it("if countPendingChanges rejects, the pending count stays at the client value without an error Snackbar", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockRejectedValueOnce(new Error("boom"));
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("snackbar")).not.toBeInTheDocument();
  });

  it("an onEditSaved call from TopologyMap increments the pending count by 1", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(0);
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "trigger-saved" }));

    expect(screen.getByRole("alert")).toHaveTextContent("1 change not yet applied");
  });

  it("Apply success shows 'Topology updated', resets the count and hides the Banner, and the Snackbar auto-dismisses after 3s", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(2);
    vi.mocked(checkmkWrite.activateChanges).mockResolvedValueOnce(undefined);
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("2 changes not yet applied");

    fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));
    await flush();

    expect(checkmkWrite.activateChanges).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("snackbar")).toHaveTextContent("Topology updated");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByTestId("snackbar")).not.toBeInTheDocument();
  });

  it("Apply failure shows a persistent 'Saved, but not live yet' Snackbar past 10s, dismissible, with the count unchanged", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(2);
    vi.mocked(checkmkWrite.activateChanges).mockRejectedValueOnce(new Error("activation failed"));
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));
    await flush();

    expect(screen.getByTestId("snackbar")).toHaveTextContent("Saved, but not live yet");
    expect(screen.getByTestId("snackbar")).toHaveTextContent(
      "Your changes are stored but Activate Changes failed. Press Apply changes again, or finish activation directly in Checkmk.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("2 changes not yet applied");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(screen.getByTestId("snackbar")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("snackbar")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("2 changes not yet applied");
  });

  it("onEditFailed from TopologyMap shows a persistent danger Snackbar with the title and body", async () => {
    renderIndex();

    fireEvent.click(screen.getByRole("button", { name: "trigger-failed" }));

    const snackbar = screen.getByTestId("snackbar");
    expect(snackbar).toHaveTextContent("Map failure");
    expect(snackbar).toHaveTextContent("Map failure body");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(screen.getByTestId("snackbar")).toBeInTheDocument();
  });

  it("5 minutes without interaction while in edit mode turns off the switch and shows an info Snackbar; a pointerdown at 4 min postpones it", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(0);
    renderIndex();
    await flush(); // let the mount-time editingAvailable probe resolve before toggling

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();
    expect((screen.getByRole("switch", { name: "Edit topology" }) as HTMLInputElement).checked).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4 * 60 * 1000);
    });
    fireEvent.pointerDown(screen.getByTestId("topology-map"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1 * 60 * 1000);
    });
    expect((screen.getByRole("switch", { name: "Edit topology" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByTestId("snackbar")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4 * 60 * 1000);
    });
    expect((screen.getByRole("switch", { name: "Edit topology" }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByTestId("snackbar")).toHaveTextContent(
      "Edit topology turned off after 5 minutes of inactivity",
    );
  });
});

describe("IndexRoute incidents (DASH-14/DASH-15)", () => {
  function seedDevicesAndIncident() {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/h1/status",
          encode({
            id: "h1",
            state: "DOWN",
            device_type: "NetworkDevice",
            timestamp: new Date().toISOString(),
          }),
        );
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/h2/status",
          encode({
            id: "h2",
            state: "UNKNOWN",
            host_state_raw: "UNREACH",
            device_type: "other",
            timestamp: new Date().toISOString(),
          }),
        );
      useAppStore
        .getState()
        .handleMessage(
          "lan/incidents/incident-h1/status",
          encode({
            id: "incident-h1",
            root: "h1",
            root_state: "DOWN",
            inferred: false,
            confirmed_down: [],
            not_observable: ["h2"],
            dependents: [],
            worst_criticality: "high",
            since: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          }),
        );
    });
  }

  it("renders the incident card in the right column (after the map), even with no host selected, and h2's tree row shows 'See incident'", () => {
    renderIndex();
    seedDevicesAndIncident();

    const incidentRegion = screen.getByRole("region", { name: /open incidents/i });
    const map = screen.getByTestId("topology-map");
    const position = incidentRegion.compareDocumentPosition(map);
    expect(position & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Collapse incidents" })).toBeInTheDocument();

    const tree = screen.getByRole("tree", { name: "Device tree" });
    within(tree)
      .getAllByRole("button")
      .forEach((button) => fireEvent.click(button));

    expect(screen.getByText("See incident")).toBeInTheDocument();
  });

  it("with a host selected, the incident region precedes the Host details pane", () => {
    renderIndexAt("/?host=h1");
    seedDevicesAndIncident();

    const incidentRegion = screen.getByRole("region", { name: /open incidents/i });
    const collapseDetails = screen.getByRole("button", { name: /collapse host details/i });
    expect(incidentRegion.compareDocumentPosition(collapseDetails) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("with no incidents open, 'No open incidents' renders and the map still renders", () => {
    renderIndex();
    expect(screen.getByText("No open incidents")).toBeInTheDocument();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("rendered at /?incident=incident-h1, that incident's card carries the highlight ring class", () => {
    renderIndexAt("/?incident=incident-h1");
    seedDevicesAndIncident();

    const card = document.querySelector('[data-incident-id="incident-h1"]');
    expect(card).toHaveClass("ring-2");
  });

  it("passes a populated incidentLookup down to TopologyMap", () => {
    renderIndex();
    seedDevicesAndIncident();
    expect(screen.getByTestId("topology-map")).toHaveAttribute("data-incident-lookup-size", "2");
  });
});

describe("IndexRoute CriticalityEditor wiring (DASH-16)", () => {
  beforeEach(() => {
    vi.mocked(checkmkWrite.countPendingChanges).mockReset().mockResolvedValue(0);
    vi.mocked(checkmkWrite.setCriticality).mockReset();
  });

  function seedTopology() {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/topology",
          encode({
            devices: [
              { id: "h1", parents: [] },
              { id: "h2", parents: [] },
            ],
          }),
        );
    });
  }

  it("the panel is absent while edit mode is off", () => {
    renderIndex();
    seedTopology();
    expect(screen.queryByRole("region", { name: "Criticality & dependencies" })).not.toBeInTheDocument();
  });

  it("with edit mode on, the panel renders under the toolbar; selecting a host via the map shows its criticality fields", async () => {
    renderIndex();
    seedTopology();
    // Wait for the mount-time editingAvailable probe to resolve and enable the switch.
    await waitFor(() => expect(screen.getByRole("switch", { name: "Edit topology" })).toBeEnabled());

    await act(async () => {
      fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    });

    expect(screen.getByRole("region", { name: "Criticality & dependencies" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Host criticality/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "trigger-select-h1" }));
    expect(screen.getByLabelText(/^Host criticality/)).toBeInTheDocument();
  });

  it("a successful editor write increments the same pending-count banner the map uses", async () => {
    vi.mocked(checkmkWrite.setCriticality).mockResolvedValueOnce(undefined);
    renderIndex();
    seedTopology();
    // Wait for the mount-time editingAvailable probe to resolve and enable the switch.
    await waitFor(() => expect(screen.getByRole("switch", { name: "Edit topology" })).toBeEnabled());

    await act(async () => {
      fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    });
    fireEvent.click(screen.getByRole("button", { name: "trigger-select-h1" }));

    const select = screen.getByLabelText(/^Host criticality/) as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: "high" } });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("1 change not yet applied");
  });
});

describe("IndexRoute host details pane (260928-l4h)", () => {
  it("at /?host=web1 shows the pane with web1's details", () => {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/web1/status",
          encode({ id: "web1", state: "OK", timestamp: new Date().toISOString() }),
        );
    });
    renderIndexAt("/?host=web1");
    expect(screen.getByRole("button", { name: /collapse host details/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "web1" })).toBeInTheDocument();
  });

  it("at / there is no pane", () => {
    renderIndex();
    expect(screen.queryByText("Host details")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /collapse host details/i })).not.toBeInTheDocument();
  });

  it("Close removes ?host= but keeps ?incident=", () => {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/incidents/incident-h1/status",
          encode({
            id: "incident-h1",
            root: "h1",
            root_state: "DOWN",
            inferred: false,
            confirmed_down: [],
            not_observable: [],
            dependents: [],
            worst_criticality: "high",
            since: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          }),
        );
    });
    renderIndexAt("/?host=web1&incident=incident-h1");
    const card = document.querySelector('[data-incident-id="incident-h1"]');
    expect(card).toHaveClass("ring-2");

    fireEvent.click(screen.getByRole("button", { name: /close host details/i }));

    expect(screen.queryByRole("button", { name: /collapse host details/i })).not.toBeInTheDocument();
    const cardAfter = document.querySelector('[data-incident-id="incident-h1"]');
    expect(cardAfter).toHaveClass("ring-2");
  });

  it("a click on empty space in the tree pane deselects the host and unfilters the event history", () => {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/web1/status",
          encode({ id: "web1", state: "OK", timestamp: new Date().toISOString() }),
        );
    });
    renderIndexAt("/?host=web1");
    expect(screen.getByTestId("event-host-filter")).toHaveTextContent("web1");
    const treeScroller = screen.getByRole("tree").parentElement as HTMLElement;

    fireEvent.click(treeScroller);

    expect(screen.queryByRole("button", { name: /collapse host details/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("event-host-filter")).not.toBeInTheDocument();
  });

  it("a click on a tree control (group toggle) does not count as an empty-space click", () => {
    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/web1/status",
          encode({ id: "web1", state: "OK", timestamp: new Date().toISOString() }),
        );
    });
    renderIndexAt("/?host=web1");
    const treeScroller = screen.getByRole("tree").parentElement as HTMLElement;
    const toggle = treeScroller.querySelector("button") as HTMLElement;
    expect(toggle).not.toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /collapse host details/i })).toBeInTheDocument();
  });
});
