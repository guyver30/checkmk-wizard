import { useState } from "react";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { Tree } from "./Tree";
import type { TreeGroupNode } from "../lib/treeModel";
import { buildTree } from "../lib/treeModel";
import { useAppStore } from "../store/useAppStore";
import { IndexRoute } from "../routes/IndexRoute";
import type { DevicePayload } from "../lib/types";
import type { IncidentLookup } from "../lib/incidents";

const NOW_MS = Date.parse("2026-09-21T12:00:00Z");
const FRESH_TIMESTAMP = new Date(NOW_MS - 5 * 1000).toISOString();

// Same reset pattern as IndexRoute.test.tsx / useAppStore.test.ts.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

function threeGroupDevices(): Record<string, DevicePayload> {
  return {
    acs1: { id: "acs1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
    nd1: { id: "nd1", device_type: "NetworkDevice", state: "WARN", timestamp: FRESH_TIMESTAMP },
    gc1: { id: "gc1", device_type: "GroupController", state: "OK", timestamp: FRESH_TIMESTAMP },
  };
}

/** Wraps Tree with lifted open-key state, exactly the shape a real caller (IndexRoute) owns. */
function TreeHarness({ groups }: { groups: TreeGroupNode[] }) {
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());
  const onToggle = (key: string) =>
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  return <Tree groups={groups} openKeys={openKeys} onToggle={onToggle} />;
}

function renderStatic(devices: Record<string, DevicePayload>, mode: "type" | "folder" = "type") {
  const groups = buildTree(devices, mode, NOW_MS);
  return render(
    <MemoryRouter>
      <Tree groups={groups} openKeys={new Set()} onToggle={() => {}} />
    </MemoryRouter>,
  );
}

/** Renders every group already expanded, so device-row links are mounted without a click. */
function renderExpanded(devices: Record<string, DevicePayload>) {
  const groups = buildTree(devices, "type", NOW_MS);
  const openKeys = new Set(groups.map((group) => group.key));
  return render(
    <MemoryRouter>
      <Tree groups={groups} openKeys={openKeys} onToggle={() => {}} />
    </MemoryRouter>,
  );
}

/** Same as renderExpanded, but threads an incidentLookup through buildTree (DASH-15). */
function renderExpandedWithLookup(devices: Record<string, DevicePayload>, incidentLookup: IncidentLookup) {
  const groups = buildTree(devices, "type", NOW_MS, { incidentLookup });
  const openKeys = new Set(groups.map((group) => group.key));
  return render(
    <MemoryRouter>
      <Tree groups={groups} openKeys={openKeys} onToggle={() => {}} />
    </MemoryRouter>,
  );
}

describe("Tree", () => {
  it("shows one group button per group, collapsed by default", () => {
    renderStatic(threeGroupDevices());
    const items = screen.getAllByRole("treeitem");
    expect(items).toHaveLength(3);
    items.forEach((item) => expect(item).toHaveAttribute("aria-expanded", "false"));
  });

  it("is multi-open: clicking two different group buttons leaves both expanded", async () => {
    const user = userEvent.setup();
    const groups = buildTree(threeGroupDevices(), "type", NOW_MS);
    render(
      <MemoryRouter>
        <TreeHarness groups={groups} />
      </MemoryRouter>,
    );
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[0]);
    await user.click(buttons[1]);
    expect(screen.getAllByRole("treeitem", { expanded: true })).toHaveLength(2);
  });

  it("shows the group label, nonOkCount/total, and a state badge for the worst state", () => {
    renderStatic(threeGroupDevices());
    const treeitems = screen.getAllByRole("treeitem");
    const networkDeviceItem = treeitems.find((item) => item.textContent?.includes("NetworkDevice"));
    expect(networkDeviceItem).toBeDefined();
    expect(within(networkDeviceItem!).getByText("1 / 1")).toBeInTheDocument();
    expect(within(networkDeviceItem!).getByText("WARN")).toBeInTheDocument();
  });

  it("shows a visible partial-data marker and an accessible name mentioning stale data when hatched", () => {
    const staleTimestamp = new Date(NOW_MS - 400 * 1000).toISOString();
    const devices: Record<string, DevicePayload> = {
      s1: { id: "s1", device_type: "ACS", state: "OK", timestamp: staleTimestamp },
      s2: { id: "s2", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP },
    };
    renderStatic(devices);
    const button = screen.getByRole("button", { name: /stale data/i });
    expect(button).toBeInTheDocument();
    expect(button.querySelector("[title*='Partial data']")).toBeInTheDocument();
  });

  it("reveals device rows with icon, label and StateBadge when a group expands", async () => {
    const user = userEvent.setup();
    const groups = buildTree(threeGroupDevices(), "type", NOW_MS);
    render(
      <MemoryRouter>
        <TreeHarness groups={groups} />
      </MemoryRouter>,
    );
    const acsButton = screen.getByRole("button", { name: /ACS/i });
    await user.click(acsButton);
    const acsRow = screen.getByText("acs1").closest('[role="treeitem"]');
    expect(acsRow).not.toBeNull();
    expect(acsRow!.querySelector('[data-device-type="ACS"]')).toBeInTheDocument();
    expect(within(acsRow as HTMLElement).getByText("OK")).toBeInTheDocument();
  });

  it("marks a device row with tagGroupMissing true with a distinguishing accessible title", async () => {
    const user = userEvent.setup();
    const devices: Record<string, DevicePayload> = {
      u1: { id: "u1", device_type: "unknown", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    const groups = buildTree(devices, "type", NOW_MS);
    render(
      <MemoryRouter>
        <TreeHarness groups={groups} />
      </MemoryRouter>,
    );
    const untypedButton = screen.getByRole("button", { name: /untyped/i });
    await user.click(untypedButton);
    expect(screen.getByTitle(/device-type tag group is absent site-wide/i)).toBeInTheDocument();
  });

  it("toggles a focused group button with Enter and Space (real <button> semantics)", async () => {
    const user = userEvent.setup();
    const groups = buildTree(threeGroupDevices(), "type", NOW_MS);
    render(
      <MemoryRouter>
        <TreeHarness groups={groups} />
      </MemoryRouter>,
    );
    const acsButton = screen.getByRole("button", { name: /ACS/i });
    acsButton.focus();
    await user.keyboard("{Enter}");
    expect(acsButton).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(acsButton).toHaveAttribute("aria-expanded", "false");
  });

  it("renders a device row as a link into its own drill-down", () => {
    const devices: Record<string, DevicePayload> = {
      web1: { id: "web1", device_type: "NetworkDevice", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    renderExpanded(devices);
    const link = screen.getByText("web1").closest("a");
    expect(link).toHaveAttribute("href", "/details?id=web1");
  });

  it("encodes a device id containing a space in its drill-down link", () => {
    const devices: Record<string, DevicePayload> = {
      "web 1": { id: "web 1", device_type: "NetworkDevice", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    renderExpanded(devices);
    const link = screen.getByText("web 1").closest("a");
    expect(link).toHaveAttribute("href", "/details?id=web%201");
  });

  it("activating a group row still calls its toggle handler rather than navigating", async () => {
    const user = userEvent.setup();
    const groups = buildTree(threeGroupDevices(), "type", NOW_MS);
    const toggled: string[] = [];
    render(
      <MemoryRouter>
        <Tree groups={groups} openKeys={new Set()} onToggle={(key) => toggled.push(key)} />
      </MemoryRouter>,
    );
    const acsButton = screen.getByRole("button", { name: /ACS/i });
    await user.click(acsButton);
    expect(toggled).toEqual(["ACS"]);
  });

  it("groups members in different folders under folder mode into distinct labelled rows", () => {
    const devices: Record<string, DevicePayload> = {
      h1: { id: "h1", folder: "Basement", state: "OK", timestamp: FRESH_TIMESTAMP },
      h2: { id: "h2", folder: "Rooftop", state: "OK", timestamp: FRESH_TIMESTAMP },
    };
    renderStatic(devices, "folder");
    expect(screen.getByRole("button", { name: /basement/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rooftop/i })).toBeInTheDocument();
  });

  it("keeps a group expanded across a store-driven re-render (IndexRoute)", async () => {
    const user = userEvent.setup();
    act(() => {
      useAppStore.setState({
        devices: {
          acs1: { id: "acs1", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
        },
      });
    });
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    const acsButton = screen.getByRole("button", { name: /ACS/i });
    await user.click(acsButton);
    expect(acsButton).toHaveAttribute("aria-expanded", "true");

    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/acs1/status",
          encode({ id: "acs1", device_type: "ACS", state: "WARN", timestamp: FRESH_TIMESTAMP }),
        );
    });

    expect(screen.getByRole("button", { name: /ACS/i })).toHaveAttribute("aria-expanded", "true");
  });

  describe("incidentLookup rendering (DASH-15)", () => {
    it("dims a consequence row, hides its state badge, and links 'See incident' to its incident", () => {
      const devices: Record<string, DevicePayload> = {
        h2: { id: "h2", device_type: "ACS", state: "UNREACH", timestamp: FRESH_TIMESTAMP },
      };
      const lookup: IncidentLookup = new Map([
        ["h2", { incidentId: "incident-h1", role: "consequence", inferred: false }],
      ]);
      renderExpandedWithLookup(devices, lookup);

      const detailsLink = screen.getByText("h2").closest("a");
      expect(detailsLink).toHaveClass("opacity-50");
      expect(detailsLink).toHaveAttribute("href", "/details?id=h2");

      const incidentLink = screen.getByText("See incident").closest("a");
      expect(incidentLink).toHaveAttribute("href", "/?incident=incident-h1");

      const deviceRow = screen.getByText("h2").closest('[role="treeitem"]');
      expect(within(deviceRow as HTMLElement).queryByText("UNREACH")).not.toBeInTheDocument();
    });

    it("shows the 'Inferred, not confirmed' badge on an inferred root row", () => {
      const devices: Record<string, DevicePayload> = {
        h1: { id: "h1", device_type: "NetworkDevice", state: "OK", timestamp: FRESH_TIMESTAMP },
      };
      const lookup: IncidentLookup = new Map([
        ["h1", { incidentId: "incident-h1", role: "root", inferred: true }],
      ]);
      renderExpandedWithLookup(devices, lookup);

      expect(screen.getByText("Inferred, not confirmed")).toBeInTheDocument();
    });

    it("renders a non-incident row unchanged: state badge present, no opacity class", () => {
      const devices: Record<string, DevicePayload> = {
        h3: { id: "h3", device_type: "ACS", state: "OK", timestamp: FRESH_TIMESTAMP },
      };
      const lookup: IncidentLookup = new Map([
        ["h1", { incidentId: "incident-h1", role: "root", inferred: false }],
      ]);
      renderExpandedWithLookup(devices, lookup);

      const detailsLink = screen.getByText("h3").closest("a");
      expect(detailsLink).not.toHaveClass("opacity-50");
      const deviceRow = screen.getByText("h3").closest('[role="treeitem"]');
      expect(within(deviceRow as HTMLElement).getByText("OK")).toBeInTheDocument();
    });
  });
});
