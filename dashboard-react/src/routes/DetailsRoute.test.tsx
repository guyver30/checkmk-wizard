import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { DetailsRoute } from "./DetailsRoute";
import { useAppStore } from "../store/useAppStore";

// Same reset pattern as IndexRoute.test.tsx: a snapshot of the store's initial state,
// replaced wholesale between tests via the test-only `true` argument.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

// DetailsRoute reads ?id= via useSearchParams(), so every render needs a router with the
// query string already in place.
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/details" element={<DetailsRoute />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DetailsRoute", () => {
  it("renders 'No device selected' when ?id= is absent", () => {
    renderAt("/details");
    expect(screen.getByText("No device selected")).toBeInTheDocument();
  });

  it("renders 'Device not found' echoing the id when the store has no matching device", () => {
    renderAt("/details?id=ghost");
    expect(screen.getByText("Device not found")).toBeInTheDocument();
    expect(screen.getByText(/ghost/)).toBeInTheDocument();
  });

  it("renders three progressbars and the headline percentages for a full-gauge device", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "OK",
          cpu_percent: 42,
          cpu_warn: 80,
          cpu_crit: 90,
          ram_percent: 91,
          ram_warn: 80,
          ram_crit: 90,
          disk_percent: 12,
          disk_warn: 80,
          disk_crit: 90,
        }),
      );
    });
    renderAt("/details?id=web1");
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();
  });

  it("hides the CPU gauge and its label when cpu_percent is null", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "OK",
          cpu_percent: null,
          ram_percent: 50,
          ram_warn: 80,
          ram_crit: 90,
          disk_percent: 50,
          disk_warn: 80,
          disk_crit: 90,
        }),
      );
    });
    renderAt("/details?id=web1");
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
    expect(screen.queryByText("CPU")).not.toBeInTheDocument();
  });

  it("renders the no-metrics message when every gauge field is null", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "OK",
          cpu_percent: null,
          ram_percent: null,
          disk_percent: null,
        }),
      );
    });
    renderAt("/details?id=web1");
    expect(screen.getByText("No agent metrics available for this device.")).toBeInTheDocument();
    expect(screen.queryAllByRole("progressbar")).toHaveLength(0);
  });

  it("renders the SMART badge from smart_total/smart_failing, hidden when smart_total is absent", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "OK",
          disk_percent: 10,
          disk_warn: 80,
          disk_crit: 90,
          smart_total: 2,
          smart_failing: 1,
        }),
      );
    });
    const failing = renderAt("/details?id=web1");
    expect(screen.getByText("SMART: Fail (1/2)")).toBeInTheDocument();
    failing.unmount();

    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web2/status",
        encode({
          id: "web2",
          state: "OK",
          disk_percent: 10,
          disk_warn: 80,
          disk_crit: 90,
          smart_total: 2,
          smart_failing: 0,
        }),
      );
    });
    const passing = renderAt("/details?id=web2");
    expect(screen.getByText("SMART: Pass (2/2)")).toBeInTheDocument();
    passing.unmount();

    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web3/status",
        encode({ id: "web3", state: "OK", disk_percent: 10, disk_warn: 80, disk_crit: 90 }),
      );
    });
    renderAt("/details?id=web3");
    expect(screen.queryByText(/^SMART:/)).not.toBeInTheDocument();
  });

  it("renders the Other mounts badge from disk_other_worst_percent", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "OK",
          disk_percent: 10,
          disk_warn: 80,
          disk_crit: 90,
          disk_other_worst_percent: 91.4,
        }),
      );
    });
    renderAt("/details?id=web1");
    expect(screen.getByText("Other mounts: 91% used")).toBeInTheDocument();
  });

  it("orders service rows worst-first (CRIT, WARN, OK) and shows plugin_output text", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "OK" }));
      useAppStore.getState().handleMessage(
        "lan/devices/web1/services",
        encode([
          { description: "Filesystem /data", state: "OK", plugin_output: "OK - 10% used" },
          { description: "Systemd Service cron", state: "CRIT", plugin_output: "CRIT - not running" },
          { description: "PING", state: "WARN", plugin_output: "WARN - high latency" },
        ]),
      );
    });
    renderAt("/details?id=web1");
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Systemd Service cron")).toBeInTheDocument();
    expect(within(rows[1]).getByText("PING")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Filesystem /data")).toBeInTheDocument();
    expect(screen.getByText("CRIT - not running")).toBeInTheDocument();
  });

  it("shows the not-yet-arrived and empty-list service copy at the right times", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "OK" }));
    });
    const notArrived = renderAt("/details?id=web1");
    expect(
      screen.getByText("Service data has not arrived yet — it should appear within one poll cycle."),
    ).toBeInTheDocument();
    notArrived.unmount();

    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/services", encode([]));
    });
    renderAt("/details?id=web1");
    expect(screen.getByText("No additional services.")).toBeInTheDocument();
  });

  it("renders history entries newest-first, and the empty-history copy when absent", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "OK" }));
    });
    const noHistory = renderAt("/details?id=web1");
    expect(screen.getByText("No recent transitions for this device.")).toBeInTheDocument();
    noHistory.unmount();

    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/history",
        encode([
          { timestamp: "2026-09-23T08:00:00Z", from: "OK", to: "WARN" },
          { timestamp: "2026-09-23T09:00:00Z", from: "WARN", to: "CRIT" },
        ]),
      );
    });
    renderAt("/details?id=web1");
    // Scoped to the History section (not the whole document) so the device's own header
    // badge can't be mistaken for a transition badge. Newest transition first (WARN -> CRIT),
    // then the older one (OK -> WARN) -- proves slice().reverse() actually flipped the
    // store's oldest-first array.
    const historySection = screen.getByText("History").closest("section");
    expect(historySection).not.toBeNull();
    const badgeTexts = within(historySection as HTMLElement)
      .getAllByText(/^(OK|WARN|CRIT)$/)
      .map((el) => el.textContent);
    expect(badgeTexts).toEqual(["WARN", "CRIT", "OK", "WARN"]);
  });
});
