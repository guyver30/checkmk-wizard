import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminActionBar, AdminBanner } from "./AdminBar";
import { __resetAdminStoreForTests, useAdminStore } from "../store/adminStore";
import { publishAdminCommand } from "../store/mqttClient";
import type { DevicePayload } from "../lib/types";

vi.mock("../store/mqttClient", () => ({
  publishAdminCommand: vi.fn(),
}));

const DEVICES = {
  sw1: { id: "sw1", alias: "Core switch" },
  h1: { id: "h1" },
  h2: { id: "h2" },
} as unknown as Record<string, DevicePayload>;

const TOPOLOGY = [
  { id: "sw1", parents: [] },
  { id: "h1", parents: ["sw1"] },
];

function renderBar(topologyDevices: unknown[] = []) {
  return render(
    <MemoryRouter>
      <AdminActionBar devices={DEVICES} topologyDevices={topologyDevices} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  __resetAdminStoreForTests();
  vi.mocked(publishAdminCommand).mockReset().mockReturnValue("cmd-1");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AdminBanner", () => {
  it("shows the zero, singular and plural variants", () => {
    const { rerender } = render(<AdminBanner />);
    expect(screen.getByText("ADMIN MODE - no hosts faked")).toBeInTheDocument();
    act(() => useAdminStore.setState({ faked: { h1: "DOWN" } }));
    rerender(<AdminBanner />);
    expect(screen.getByText("ADMIN MODE - 1 host faked")).toBeInTheDocument();
    act(() =>
      useAdminStore.setState({
        faked: { h1: "DOWN", h2: "UP", sw1: "UNREACH" },
      }),
    );
    expect(screen.getByText("ADMIN MODE - 3 hosts faked")).toBeInTheDocument();
  });

  it("has role status and no dismiss control", () => {
    render(<AdminBanner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the config error instead of the banner text", () => {
    useAdminStore.setState({ configError: true });
    render(<AdminBanner />);
    expect(screen.getByText(/Admin login unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/ADMIN MODE/)).toBeNull();
  });
});

describe("AdminActionBar", () => {
  it("disables actions with nothing selected and shows the empty hint", () => {
    renderBar();
    expect(screen.getByText("No hosts selected")).toBeInTheDocument();
    expect(screen.getByText(/Ctrl\+click hosts/)).toBeInTheDocument();
    for (const name of [
      "Set UP",
      "Set DOWN",
      "Set UNREACHABLE",
      "Restore selected",
      "Restore all",
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("disables every action when configError is set", () => {
    useAdminStore.setState({
      selected: new Set(["h1"]),
      faked: { h2: "DOWN" },
      configError: true,
    });
    renderBar();
    expect(screen.getByRole("button", { name: "Set DOWN" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore all" })).toBeDisabled();
  });

  it("opens a dialog listing the hosts and does not publish before confirm", () => {
    useAdminStore.setState({ selected: new Set(["h1", "h2"]) });
    renderBar();
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set DOWN" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(
      "Mark 2 hosts DOWN. Managed hosts below them become UNREACHABLE.",
    );
    expect(dialog).toHaveTextContent("h1");
    expect(dialog).toHaveTextContent("h2");
    expect(publishAdminCommand).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("splits selected and cascaded hosts for Set DOWN", () => {
    useAdminStore.setState({ selected: new Set(["sw1"]) });
    renderBar(TOPOLOGY);
    fireEvent.click(screen.getByRole("button", { name: "Set DOWN" }));
    expect(screen.getByText("Selected (1)")).toBeInTheDocument();
    expect(screen.getByText("Also set UNREACHABLE (1)")).toBeInTheDocument();
    expect(screen.getByText("Core switch")).toBeInTheDocument();
  });

  it("closes without publishing on Cancel, Escape and scrim click", () => {
    useAdminStore.setState({ selected: new Set(["h1"]) });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.click(screen.getByTestId("admin-scrim"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(publishAdminCommand).not.toHaveBeenCalled();
  });

  it("publishes on confirm, then closes and shows Sent on a successful ack", () => {
    useAdminStore.setState({ selected: new Set(["h1", "h2"]) });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Set DOWN" }));
    fireEvent.click(screen.getByRole("button", { name: "Set 2 hosts DOWN" }));
    expect(publishAdminCommand).toHaveBeenCalledTimes(1);
    expect(publishAdminCommand).toHaveBeenCalledWith("down", ["h1", "h2"]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() =>
      useAdminStore.setState({
        lastResult: {
          ok: true,
          action: "down",
          count: 2,
          detail: "",
          atMs: Date.now(),
        },
      }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Sent: 2 hosts set DOWN")).toBeInTheDocument();
  });

  it("shows the failure text for a negative ack", () => {
    useAdminStore.setState({ selected: new Set(["h1"]) });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.click(screen.getByRole("button", { name: "Set 1 hosts UP" }));
    act(() =>
      useAdminStore.setState({
        lastResult: {
          ok: false,
          action: "up",
          count: 0,
          detail: "livestatus down",
          atMs: Date.now(),
        },
      }),
    );
    expect(
      screen.getByText(
        "Could not apply: livestatus down. Nothing changed. Try again in a few seconds.",
      ),
    ).toBeInTheDocument();
  });

  it("calls expirePending after 15 s without an ack and shows the no-answer text", () => {
    vi.useFakeTimers();
    useAdminStore.setState({
      selected: new Set(["h1"]),
      pending: { id: "cmd-1", action: "up", hosts: ["h1"], sentAtMs: 0 },
    });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.click(screen.getByRole("button", { name: "Set 1 hosts UP" }));
    act(() => {
      vi.advanceTimersByTime(15000);
    });
    expect(
      screen.getByText(
        "No answer from the poller. Check that it is running, then try again.",
      ),
    ).toBeInTheDocument();
    expect(useAdminStore.getState().pending).toBeNull();
  });

  it("shows a not-connected failure when publish returns null", () => {
    vi.mocked(publishAdminCommand).mockReturnValue(null);
    useAdminStore.setState({ selected: new Set(["h1"]) });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Set UP" }));
    fireEvent.click(screen.getByRole("button", { name: "Set 1 hosts UP" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(/not connected to the broker/)).toBeInTheDocument();
  });

  it("Restore all publishes restore_all with no hosts", () => {
    useAdminStore.setState({ faked: { h1: "DOWN", h2: "UP" } });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Restore all" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "Re-enable normal checks on all 2 faked hosts.",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Restore all 2 faked hosts" }),
    );
    expect(publishAdminCommand).toHaveBeenCalledWith("restore_all", []);
  });

  it("Escape and Clear selection clear the selection when no dialog is open", () => {
    useAdminStore.setState({ selected: new Set(["h1"]) });
    renderBar();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useAdminStore.getState().selected.size).toBe(0);
    act(() => useAdminStore.setState({ selected: new Set(["h2"]) }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(useAdminStore.getState().selected.size).toBe(0);
  });
});
