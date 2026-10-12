import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveredHostsBanner } from "./DiscoveredHostsBanner";
import * as checkmkWrite from "../lib/checkmkWrite";

// Network-touching functions are mocked; the pure parsing helpers stay real so the banner is
// exercised against the same classification the app uses. The pending-change shape itself is
// not live-verified, so these fixtures use the phrasing the parser is written to tolerate.
vi.mock("../lib/checkmkWrite", async () => ({
  ...(await vi.importActual<typeof import("../lib/checkmkWrite")>("../lib/checkmkWrite")),
  listPendingChanges: vi.fn(),
  getHostSummary: vi.fn(),
  activateChanges: vi.fn(),
}));

const listPending = vi.mocked(checkmkWrite.listPendingChanges);
const hostSummary = vi.mocked(checkmkWrite.getHostSummary);
const activate = vi.mocked(checkmkWrite.activateChanges);

const HOST_A = { id: "1", user_id: "cmkadmin", text: "Created new host web01." };
const HOST_B = { id: "2", user_id: "cmkadmin", text: "Created new host web02." };
const OTHER = (n: number) => ({ id: `o${n}`, user_id: "bob", text: `Modified folder f${n}.` });

function renderBanner(props: Partial<React.ComponentProps<typeof DiscoveredHostsBanner>> = {}) {
  const onActivated = vi.fn();
  const onFailed = vi.fn();
  const view = render(
    <DiscoveredHostsBanner enabled onActivated={onActivated} onFailed={onFailed} {...props} />,
  );
  return { ...view, onActivated, onFailed };
}

beforeEach(() => {
  sessionStorage.clear();
  listPending.mockReset().mockResolvedValue([]);
  hostSummary.mockReset().mockImplementation(async (name) => ({
    name,
    ip: name === "web01" ? "10.0.0.1" : "10.0.0.2",
    folder: "/lab",
  }));
  activate.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DiscoveredHostsBanner", () => {
  it("lists each foreign-created host with its IP and folder", async () => {
    listPending.mockResolvedValue([HOST_A, HOST_B]);
    renderBanner();
    expect(await screen.findByText(/web01 - 10\.0\.0\.1 - \/lab/)).toBeInTheDocument();
    expect(await screen.findByText(/web02 - 10\.0\.0\.2 - \/lab/)).toBeInTheDocument();
  });

  it("shows IP unknown for a host whose lookup fails, keeping the other host", async () => {
    listPending.mockResolvedValue([HOST_A, HOST_B]);
    hostSummary.mockImplementation(async (name) => {
      if (name === "web01") throw new Error("404");
      return { name, ip: "10.0.0.2", folder: "/lab" };
    });
    renderBanner();
    expect(await screen.findByText(/web01 - IP unknown - \//)).toBeInTheDocument();
    expect(await screen.findByText(/web02 - 10\.0\.0\.2/)).toBeInTheDocument();
  });

  it("renders nothing for own changes only, no changes, or foreign non-host changes only", async () => {
    listPending.mockResolvedValue([
      { id: "x", user_id: "topology_editor", text: "Created new host mine." },
      OTHER(1),
    ]);
    renderBanner();
    await waitFor(() => expect(listPending).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument();
  });

  it("falls back to a generic banner for unparseable host creations or unknown shapes", async () => {
    listPending.mockResolvedValue([
      { id: "1", user_id: "cmkadmin", action_name: "create-host", text: "Odd phrasing" },
      { id: "2", user_id: "cmkadmin" },
    ]);
    renderBanner();
    expect(await screen.findByText("2 pending changes awaiting activation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not now" })).toBeInTheDocument();
  });

  it("activates immediately with the shown keys when no other foreign changes ride along", async () => {
    listPending.mockResolvedValue([HOST_A, HOST_B]);
    // Once activation succeeds Checkmk has nothing pending any more.
    activate.mockImplementation(async () => {
      listPending.mockResolvedValue([]);
    });
    const { onActivated } = renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    await waitFor(() => expect(onActivated).toHaveBeenCalledWith(2));
    expect(activate).toHaveBeenCalledWith({
      forceForeignChanges: true,
      expectedChangeKeys: ["1", "2"],
    });
    await waitFor(() =>
      expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument(),
    );
  });

  it("requires a second confirmation naming the other users' changes", async () => {
    listPending.mockResolvedValue([HOST_A, OTHER(1), OTHER(2)]);
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    expect(activate).not.toHaveBeenCalled();
    expect(screen.getByText(/2 other pending changes by other users will also go/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Activate all" }));
    await waitFor(() =>
      expect(activate).toHaveBeenCalledWith(expect.objectContaining({ forceForeignChanges: true })),
    );
  });

  it("on a 409 reloads and asks the operator to confirm again", async () => {
    listPending.mockResolvedValue([HOST_A]);
    activate.mockRejectedValue(
      new checkmkWrite.CheckmkWriteError("GET", "u", 409, "pending changes changed since confirmation"),
    );
    const { onFailed } = renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    expect(await screen.findByText(/review the list and confirm again/)).toBeInTheDocument();
    expect(onFailed).not.toHaveBeenCalled();
    expect(listPending.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("calls onFailed for any other activation error", async () => {
    listPending.mockResolvedValue([HOST_A]);
    activate.mockRejectedValue(new checkmkWrite.CheckmkWriteError("POST", "u", 500, "boom"));
    const { onFailed } = renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    await waitFor(() => expect(onFailed).toHaveBeenCalled());
  });

  it("Not now hides the banner, persists across remount, and reappears for a new change", async () => {
    listPending.mockResolvedValue([HOST_A]);
    const first = renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("discoveredHostsBanner.dismissed")).toBe('["1"]');
    first.unmount();

    renderBanner();
    await waitFor(() => expect(listPending).toHaveBeenCalledTimes(2));
    await act(async () => {});
    expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument();
    cleanup();

    listPending.mockResolvedValue([HOST_A, HOST_B]);
    renderBanner();
    expect(await screen.findByText(/web02/)).toBeInTheDocument();
  });

  it("still hides for the mount when sessionStorage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    listPending.mockResolvedValue([HOST_A]);
    renderBanner();
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument();
  });

  it("does not read pending changes and renders nothing when disabled", async () => {
    renderBanner({ enabled: false });
    await act(async () => {});
    expect(listPending).not.toHaveBeenCalled();
    expect(screen.queryByTestId("discovered-hosts-banner")).not.toBeInTheDocument();
  });
});
