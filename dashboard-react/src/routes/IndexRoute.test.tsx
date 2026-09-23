import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndexRoute } from "./IndexRoute";
import * as checkmkWrite from "../lib/checkmkWrite";
import { useAppStore } from "../store/useAppStore";

// Every write in edit mode goes through checkmkWrite.ts -- mocked here so these route-level
// tests exercise IndexRoute's own wiring (what it calls, how it reacts to success/failure)
// without making a real network call, the same convention TopologyMap.test.tsx already uses.
vi.mock("../lib/checkmkWrite", () => ({
  countPendingChanges: vi.fn(),
  activateChanges: vi.fn(),
}));

// isTopologyEditingConfigured() reads the placeholder secret in config.ts, which stays
// unconfigured in this checkout -- forced true here so the Switch/toolbar tests below don't
// need to also cover the disabled-hint state (TopologyToolbar.test.tsx already covers that).
vi.mock("../lib/config", async () => {
  const actual = await vi.importActual<typeof import("../lib/config")>("../lib/config");
  return { ...actual, isTopologyEditingConfigured: () => true };
});

// TopologyMap itself is exercised by TopologyMap.test.tsx (including its real onEditSaved/
// onEditFailed call sites via vis-network's manipulation toolbar); here it's replaced with a
// stand-in exposing the same props IndexRoute wires, so these tests can trigger
// onEditSaved/onEditFailed directly without driving a real vis-network instance.
vi.mock("../components/TopologyMap", () => ({
  TopologyMap: (props: {
    editMode?: boolean;
    onEditSaved?: () => void;
    onEditFailed?: (failure: { title: string; body: string }) => void;
  }) => (
    <div data-testid="topology-map" data-edit-mode={String(props.editMode ?? false)}>
      <button onClick={() => props.onEditSaved?.()}>trigger-saved</button>
      <button onClick={() => props.onEditFailed?.({ title: "Map failure", body: "Map failure body" })}>
        trigger-failed
      </button>
    </div>
  ),
}));

// Same reset pattern as useAppStore.test.ts: a snapshot of the store's initial state, replaced
// wholesale between tests via the test-only `true` argument.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
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

describe("IndexRoute", () => {
  it("renders the stats strip before the topology map, in document order", () => {
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    const status = screen.getByRole("status", { name: /fleet state summary/i });
    const map = screen.getByTestId("topology-map");
    // DOCUMENT_POSITION_FOLLOWING (4) set on `map` relative to `status` means status comes
    // first in document order.
    const position = status.compareDocumentPosition(map);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("updates the strip's counts in place without remounting the topology map", () => {
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    const mapBefore = screen.getByTestId("topology-map");

    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/h1/status",
          encode({ id: "h1", state: "DOWN", timestamp: new Date().toISOString() }),
        );
    });

    const status = screen.getByRole("status", { name: /fleet state summary/i });
    expect(within(status).getByText("DOWN")).toBeInTheDocument();
    const mapAfter = screen.getByTestId("topology-map");
    expect(mapAfter).toBe(mapBefore);
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

  it("turning the switch on calls countPendingChanges once and shows its result as the pending count", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(2);
    renderIndex();

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    expect(checkmkWrite.countPendingChanges).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("2 changes not yet applied");
  });

  it("if countPendingChanges rejects, the pending count stays at the client value without an error Snackbar", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockRejectedValueOnce(new Error("boom"));
    renderIndex();

    fireEvent.click(screen.getByRole("switch", { name: "Edit topology" }));
    await flush();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("snackbar")).not.toBeInTheDocument();
  });

  it("an onEditSaved call from TopologyMap increments the pending count by 1", async () => {
    vi.mocked(checkmkWrite.countPendingChanges).mockResolvedValueOnce(0);
    renderIndex();

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
