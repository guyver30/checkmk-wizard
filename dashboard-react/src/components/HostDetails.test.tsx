import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostDetails } from "./HostDetails";
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

// HostDetails takes its host id as a prop -- no router needed to render it directly.
function renderAt(id: string) {
  return render(<HostDetails id={id} />);
}

describe("HostDetails", () => {
  it("renders 'Device not found' echoing the id when the store has no matching device", () => {
    renderAt("ghost");
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
    renderAt("web1");
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();
  });

  // Regression (quick 261008-d0w): CPU load WARN produced no notification/need and had no visible cause.
  it("renders the CPU load gauge right after the CPU utilisation gauge", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({
          id: "web1",
          state: "WARN",
          cpu_percent: 42,
          cpu_warn: 80,
          cpu_crit: 90,
          cpu_load1: 3.1,
          cpu_load5: 2.5,
          cpu_load15: 1.2,
          cpu_load_warn: 3,
          cpu_load_crit: 4,
          ram_percent: 50,
          disk_percent: 50,
        }),
      );
    });
    renderAt("web1");
    const load = screen.getByLabelText("CPU load");
    expect(within(load).getByText("3.10")).toBeInTheDocument();
    expect(within(load).getByText("Load")).toBeInTheDocument();
    expect(within(load).getByText("1/5/15 min: 3.10 / 2.50 / 1.20")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(4);
    expect(screen.getByLabelText("CPU utilisation").nextElementSibling).toBe(load);
  });

  it("hides the CPU load gauge when cpu_load1 is null", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({ id: "web1", state: "OK", cpu_percent: 42, cpu_load1: null, ram_percent: 50, disk_percent: 50 }),
      );
    });
    renderAt("web1");
    expect(screen.queryByLabelText("CPU load")).not.toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
  });

  it("shows the gauge row when only cpu_load1 is set", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({ id: "web1", state: "OK", cpu_load1: 0.5 }),
      );
    });
    renderAt("web1");
    expect(screen.getByLabelText("CPU load")).toBeInTheDocument();
    expect(screen.queryByText("No agent metrics available for this device.")).not.toBeInTheDocument();
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
    renderAt("web1");
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
    renderAt("web1");
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
    const failing = renderAt("web1");
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
    const passing = renderAt("web2");
    expect(screen.getByText("SMART: Pass (2/2)")).toBeInTheDocument();
    passing.unmount();

    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web3/status",
        encode({ id: "web3", state: "OK", disk_percent: 10, disk_warn: 80, disk_crit: 90 }),
      );
    });
    renderAt("web3");
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
    renderAt("web1");
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
    renderAt("web1");
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Systemd Service cron")).toBeInTheDocument();
    expect(within(rows[1]).getByText("PING")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Filesystem /data")).toBeInTheDocument();
    expect(screen.getByText("CRIT - not running")).toBeInTheDocument();
  });

  it("shows only the focused agent view for an agent host", () => {
    act(() => {
      useAppStore.getState().handleMessage(
        "lan/devices/web1/status",
        encode({ id: "web1", state: "OK", cpu_percent: 10, ram_percent: 20, disk_percent: 30 }),
      );
      useAppStore.getState().handleMessage(
        "lan/devices/web1/services",
        encode([
          { description: "Check_MK Agent", state: "OK", plugin_output: "Version: 2.4.0p35" },
          { description: "Check_MK", state: "OK", plugin_output: "Success" },
          { description: "Uptime", state: "OK", plugin_output: "Up since Sep 20, uptime: 5 days" },
          { description: "Systemd Service ssh", state: "OK", plugin_output: "Running" },
          { description: "TCP Port 22 (expected open)", state: "OK", plugin_output: "TCP OK" },
          { description: "Interface 2", state: "OK", plugin_output: "should not be shown" },
          { description: "PING", state: "OK", plugin_output: "should not be shown either" },
        ]),
      );
    });
    renderAt("web1");
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Up since Sep 20, uptime: 5 days")).toBeInTheDocument();
    expect(screen.getByText("Systemd Service ssh")).toBeInTheDocument();
    expect(screen.getByText("TCP Port 22 (expected open)")).toBeInTheDocument();
    // Only the services table has an Output column; the TCP-port table does not.
    expect(screen.getAllByRole("columnheader", { name: "Output" })).toHaveLength(1);
    expect(screen.queryByText("Interface 2")).not.toBeInTheDocument();
    expect(screen.queryByText("PING")).not.toBeInTheDocument();
    // The old event-history section had a "History" heading; the CPU gauges now carry History buttons (quick 261008-kr3), so only the heading is asserted absent.
    expect(screen.queryByRole("heading", { name: "History" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
  });

  it("shows 'Not connected' when the agent connection check is not OK", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "CRIT" }));
      useAppStore.getState().handleMessage(
        "lan/devices/web1/services",
        encode([
          { description: "Check_MK Agent", state: "OK", plugin_output: "" },
          { description: "Check_MK", state: "CRIT", plugin_output: "Timeout" },
        ]),
      );
    });
    renderAt("web1");
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("No services were selected for monitoring in the wizard.")).toBeInTheDocument();
  });

  it("shows the not-yet-arrived and empty-list service copy at the right times", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "OK" }));
    });
    const notArrived = renderAt("web1");
    expect(
      screen.getByText("Service data has not arrived yet — it should appear within one poll cycle."),
    ).toBeInTheDocument();
    notArrived.unmount();

    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/services", encode([]));
    });
    renderAt("web1");
    expect(screen.getByText("No additional services.")).toBeInTheDocument();
  });

  describe("failure prediction", () => {
    function seedHost(id = "web1") {
      useAppStore.getState().handleMessage(`lan/devices/${id}/status`, encode({ id, state: "OK" }));
    }
    function seedNeed(over: Record<string, unknown>) {
      useAppStore.getState().handleMessage(
        `lan/needs/${over.id}/status`,
        encode({ host: "web1", tier: "urgent", source: "trend", service: "Filesystem /", metric: "fs_used_percent", ...over }),
      );
    }
    function seedForecast(fits: Record<string, unknown>[], host = "web1") {
      useAppStore.getState().handleMessage(`lan/forecasts/${host}`, encode({ host, generated_at: "2026-10-04T10:00:00Z", fits }));
    }
    beforeEach(() => {
      // The chart dialog fetches history; a never-resolving fetch keeps it in its loading state.
      vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    });
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("lists the host's visible needs with narration, excluding cancelled and other hosts' needs", () => {
      act(() => {
        seedHost();
        seedNeed({
          id: "n1",
          crit_date: "2026-10-20T00:00:00Z",
          confidence: "medium",
          history_days: 21,
          narration: "Disk fills up in about two weeks.",
        });
        seedNeed({ id: "n2", tier: "immediate", source: "failure", service: "PING", metric: "", since: "2026-10-04T08:15:00Z", narration: "Ping is failing." });
        seedNeed({ id: "n3", triage: { action: "cancel", tier: "urgent", set_at: "2026-10-04T09:00:00Z", by: "op" }, service: "Cancelled svc" });
        seedNeed({ id: "n4", host: "other", service: "Other host svc" });
      });
      renderAt("web1");
      expect(screen.getByText("Service needs")).toBeInTheDocument();
      expect(screen.getByText("Immediate")).toBeInTheDocument();
      expect(screen.getByText("Urgent")).toBeInTheDocument();
      expect(screen.getByText("Filesystem / · fs_used_percent")).toBeInTheDocument();
      expect(screen.getByText(/^Critical by 20 Oct/)).toBeInTheDocument();
      expect(screen.getByText("Confidence: medium")).toBeInTheDocument();
      expect(screen.getByText("21 days of history")).toBeInTheDocument();
      expect(screen.getByText("Disk fills up in about two weeks.")).toBeInTheDocument();
      expect(screen.getByText("Ping is failing.")).toBeInTheDocument();
      expect(screen.queryByText("Cancelled svc")).not.toBeInTheDocument();
      expect(screen.queryByText("Other host svc")).not.toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "View chart" })).toHaveLength(1);
      expect(screen.queryByText(/Triage/)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Triage/ })).not.toBeInTheDocument();
    });

    it("omits the Service needs heading when the host has no needs", () => {
      act(() => {
        seedHost();
        seedNeed({ id: "n4", host: "other" });
      });
      renderAt("web1");
      expect(screen.queryByText("Service needs")).toBeNull();
    });

    it("opens the forecast chart from View chart", () => {
      act(() => {
        seedHost();
        seedNeed({ id: "n1", crit_date: "2026-10-20T00:00:00Z", confidence: "high" });
      });
      renderAt("web1");
      fireEvent.click(screen.getByRole("button", { name: "View chart" }));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("lists every fit under Trends with value, unit and caption", () => {
      act(() => {
        seedHost();
        seedForecast([
          { service: "Filesystem /", metric: "fs_used_percent", unit: "%", status: "trending", last_value: 71.26, crit_date: "2026-10-20T00:00:00Z" },
          { service: "Memory", metric: "mem_used_percent", unit: "%", status: "stable", last_value: 40 },
          { service: "CPU", metric: "util", unit: "%", status: "no_clear_trend", last_value: 12 },
        ]);
      });
      renderAt("web1");
      expect(screen.getByText("Trends")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Filesystem \/ · fs_used_percent 71\.3 % Trending, Critical by 20 Oct/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Memory · mem_used_percent 40 % Stable" })).toBeInTheDocument();
      // Operator decision of quick 261008-kr3, not a regression: utilization is history-only and
      // is reached from the CPU gauge, so the Trends list no longer lists it.
      expect(screen.queryByRole("button", { name: /CPU · util/ })).toBeNull();
    });

    it("omits the Trends section when only history-only fits exist", () => {
      act(() => {
        seedHost();
        seedForecast([{ service: "CPU utilization", metric: "util", unit: "%", status: "no_clear_trend", last_value: 12 }]);
      });
      renderAt("web1");
      expect(screen.queryByText("Trends")).toBeNull();
    });

    it("opens the chart for a stable metric with no need and returns focus on close", () => {
      act(() => {
        seedHost();
        seedForecast([{ service: "Memory", metric: "mem_used_percent", unit: "%", status: "stable", last_value: 40 }]);
      });
      renderAt("web1");
      const entry = screen.getByRole("button", { name: /Stable/ });
      fireEvent.click(entry);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(entry).toHaveFocus();
    });

    it("omits Trends when the host has no forecast", () => {
      act(() => {
        seedHost();
      });
      renderAt("web1");
      expect(screen.queryByText("Trends")).toBeNull();
    });
  });

  describe("CPU history buttons", () => {
    function seedGauges() {
      act(() => {
        useAppStore.getState().handleMessage(
          "lan/devices/web1/status",
          encode({
            id: "web1",
            state: "OK",
            cpu_percent: 42,
            cpu_warn: 80,
            cpu_crit: 90,
            cpu_load1: 1.1,
            cpu_load5: 0.9,
            cpu_load15: 0.7,
            cpu_load_warn: 3,
            cpu_load_crit: 4,
          }),
        );
      });
    }
    function stubFetch() {
      const fn = vi.fn(async (url: string) => {
        const m = new URL(url, "http://x").searchParams.get("param_m") ?? "";
        const t0 = Date.now() / 1000;
        const data = Array.from({ length: 48 }, (_, i) => ({ t: t0 - (48 - i) * 3600, v: m === "util" ? 40 : 1 }));
        return new Response(JSON.stringify({ data }), { status: 200 });
      });
      vi.stubGlobal("fetch", fn);
      return fn;
    }
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("keeps the gauge columns and adds a History button to the CPU and Load ones", () => {
      seedGauges();
      stubFetch();
      renderAt("web1");
      const cpu = screen.getByLabelText("CPU utilisation");
      const load = screen.getByLabelText("CPU load");
      expect(cpu.nextElementSibling).toBe(load);
      expect(within(cpu).getByRole("button", { name: "CPU utilisation history" })).toHaveTextContent("History");
      expect(within(load).getByRole("button", { name: "CPU load history" })).toHaveTextContent("History");
    });

    it("opens the utilization history without forecast badges and returns focus on close", async () => {
      seedGauges();
      stubFetch();
      renderAt("web1");
      const button = screen.getByRole("button", { name: "CPU utilisation history" });
      fireEvent.click(button);
      expect(screen.getByRole("heading", { name: "web1 · CPU utilization util" })).toBeInTheDocument();
      expect(screen.getByRole("dialog").textContent).not.toMatch(/Confidence|No forecast yet|Stable|No clear trend/);
      await waitFor(() => expect(screen.getByText("Warn 80%")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(button).toHaveFocus();
    });

    it("opens the load history with three series and the absolute levels, and zooms", async () => {
      seedGauges();
      const fn = stubFetch();
      renderAt("web1");
      const button = screen.getByRole("button", { name: "CPU load history" });
      fireEvent.click(button);
      expect(screen.getByRole("heading", { name: "web1 · CPU load" })).toBeInTheDocument();
      await waitFor(() => expect(screen.getAllByTestId("history-series")).toHaveLength(3));
      expect(screen.getByText("Warn 3")).toBeInTheDocument();
      expect(screen.getByText("Crit 4")).toBeInTheDocument();
      const metrics = fn.mock.calls.map(([url]) => new URL(url, "http://x").searchParams.get("param_m")).sort();
      expect(metrics).toEqual(["load1", "load15", "load5"]);
      fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
      expect(screen.getByRole("img").getAttribute("data-zoomed")).toBe("true");
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(button).toHaveFocus();
    });
  });

  it("shows no history section; history lives in the event history pane (260928 follow-up)", () => {
    act(() => {
      useAppStore.getState().handleMessage("lan/devices/web1/status", encode({ id: "web1", state: "OK" }));
    });
    renderAt("web1");
    expect(screen.queryByText("History")).not.toBeInTheDocument();
    expect(screen.queryByText("No recent transitions for this device.")).not.toBeInTheDocument();
  });
});
