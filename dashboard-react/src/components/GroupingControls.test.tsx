import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { IndexRoute } from "../routes/IndexRoute";
import { useAppStore } from "../store/useAppStore";
import type { DevicePayload } from "../lib/types";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();

// Same reset pattern as IndexRoute.test.tsx / Tree.test.tsx.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
  localStorage.clear();
});

function threeGroupDevices(): Record<string, DevicePayload> {
  return {
    acs1: { id: "acs1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP, folder: "Basement" },
    nd1: { id: "nd1", device_type: "NetworkDevice", state: "WARN", timestamp: FRESH_TIMESTAMP, folder: "Rooftop" },
    gc1: {
      id: "gc1",
      device_type: "GroupController",
      state: "DOWN",
      timestamp: FRESH_TIMESTAMP,
      folder: "Basement",
    },
  };
}

function setDevices(devices: Record<string, DevicePayload>) {
  act(() => {
    useAppStore.setState({ devices });
  });
}

function renderIndex() {
  return render(
    <MemoryRouter>
      <IndexRoute />
    </MemoryRouter>,
  );
}

describe("GroupingControls (wired into IndexRoute)", () => {
  it("renders a labelled select offering 'Group by type' and 'Group by folder', plus a labelled 'Order by severity' checkbox", () => {
    setDevices(threeGroupDevices());
    renderIndex();
    const select = screen.getByLabelText(/group by/i);
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Group by type" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Group by folder" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /order by severity/i })).toBeInTheDocument();
  });

  it("selecting 'Group by folder' re-groups the tree under folder-derived labels", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    await user.selectOptions(screen.getByLabelText(/group by/i), "folder");
    expect(screen.getByRole("button", { name: /basement/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rooftop/i })).toBeInTheDocument();
  });

  it("checking 'Order by severity' reorders groups so the worst-state group is first", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    // Default (unchecked) order is alphabetical: ACS, GroupController, NetworkDevice.
    let treeitems = screen.getAllByRole("treeitem");
    expect(treeitems[0].textContent).toContain("ACS");

    await user.click(screen.getByRole("checkbox", { name: /order by severity/i }));

    // GroupController has the worst state (DOWN), so it must sort first once ordering is on.
    treeitems = screen.getAllByRole("treeitem");
    expect(treeitems[0].textContent).toContain("GroupController");
  });

  it("expanding two groups, then toggling 'Order by severity', leaves both groups expanded", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    await user.click(screen.getByRole("button", { name: /ACS/i }));
    await user.click(screen.getByRole("button", { name: /NetworkDevice/i }));
    expect(screen.getAllByRole("treeitem", { expanded: true })).toHaveLength(2);

    const firstRowBefore = screen.getAllByRole("treeitem")[0].textContent;
    await user.click(screen.getByRole("checkbox", { name: /order by severity/i }));

    expect(screen.getAllByRole("treeitem", { expanded: true })).toHaveLength(2);
    const firstRowAfter = screen.getAllByRole("treeitem")[0].textContent;
    // Proves the order actually changed while expansion state did not.
    expect(firstRowAfter).not.toBe(firstRowBefore);
  });

  it("switching grouping mode does not throw and does not leave a stale expanded row for a group key that no longer exists", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    await user.click(screen.getByRole("button", { name: /ACS/i }));
    expect(screen.getAllByRole("treeitem", { expanded: true })).toHaveLength(1);

    await expect(
      user.selectOptions(screen.getByLabelText(/group by/i), "folder"),
    ).resolves.not.toThrow();

    // "ACS" is a type-mode-only key; it cannot appear as an expanded group under folder mode.
    // queryAllByRole (not getAllByRole) tolerates the zero-matches case: pruning stale keys
    // may legitimately leave nothing expanded, which is itself a passing outcome here.
    const expandedAfter = screen.queryAllByRole("treeitem", { expanded: true });
    expandedAfter.forEach((item) => expect(item.textContent).not.toContain("ACS"));
  });

  it("switches grouping mode twice and leaves no stale group key expanded for a key absent from the current tree", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    await user.click(screen.getByRole("button", { name: /ACS/i }));
    await user.selectOptions(screen.getByLabelText(/group by/i), "folder");
    await user.click(screen.getByRole("button", { name: /basement/i }));
    await user.selectOptions(screen.getByLabelText(/group by/i), "type");

    const expandedAfter = screen.queryAllByRole("treeitem", { expanded: true });
    expandedAfter.forEach((item) => expect(item.textContent).not.toContain("Basement"));
  });

  it("both controls are reachable and operable by keyboard alone", async () => {
    const user = userEvent.setup();
    setDevices(threeGroupDevices());
    renderIndex();
    const select = screen.getByLabelText(/group by/i) as HTMLSelectElement;
    const checkbox = screen.getByRole("checkbox", { name: /order by severity/i }) as HTMLInputElement;

    select.focus();
    expect(select).toHaveFocus();

    await user.tab();
    expect(checkbox).toHaveFocus();

    expect(checkbox.checked).toBe(false);
    await user.keyboard(" ");
    expect(checkbox.checked).toBe(true);
  });
});
