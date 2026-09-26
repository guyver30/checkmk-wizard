import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CriticalityEditor } from "./CriticalityEditor";
import * as checkmkWrite from "../lib/checkmkWrite";
import type { TopologyNode } from "../lib/types";

vi.mock("../lib/checkmkWrite", () => ({
  setCriticality: vi.fn(),
  setServiceCriticality: vi.fn(),
  updateDependsOn: vi.fn(),
}));

const nameFor = (id: string) => id;

function renderEditor(overrides: Partial<React.ComponentProps<typeof CriticalityEditor>> = {}) {
  const onSaved = vi.fn();
  const onFailed = vi.fn();
  const props: React.ComponentProps<typeof CriticalityEditor> = {
    hostIds: ["h1", "h2", "h3"],
    nameFor,
    selectedHost: null,
    onSelectHost: vi.fn(),
    node: undefined,
    serviceNames: [],
    onSaved,
    onFailed,
    ...overrides,
  };
  const view = render(<CriticalityEditor {...props} />);
  return { ...view, onSaved, onFailed, props };
}

beforeEach(() => {
  vi.mocked(checkmkWrite.setCriticality).mockReset();
  vi.mocked(checkmkWrite.setServiceCriticality).mockReset();
  vi.mocked(checkmkWrite.updateDependsOn).mockReset();
});

describe("CriticalityEditor", () => {
  it("with selectedHost null, shows the Device select and the selection hint", () => {
    renderEditor();
    expect(screen.getByLabelText(/^Device/)).toBeInTheDocument();
    expect(
      screen.getByText("Select a device on the map or from the list to edit its criticality."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Host criticality/)).not.toBeInTheDocument();
  });

  it("with a selectedHost, shows Host criticality prefilled from the topology node (default low)", () => {
    renderEditor({ selectedHost: "h1", node: { id: "h1" } as TopologyNode });
    const select = screen.getByLabelText(/^Host criticality/) as HTMLSelectElement;
    expect(select.value).toBe("low");
  });

  it("prefills Host criticality from node.criticality when set", () => {
    renderEditor({ selectedHost: "h1", node: { id: "h1", criticality: "high" } as TopologyNode });
    const select = screen.getByLabelText(/^Host criticality/) as HTMLSelectElement;
    expect(select.value).toBe("high");
  });

  it("changing Host criticality calls setCriticality and, on success, calls onSaved once", async () => {
    vi.mocked(checkmkWrite.setCriticality).mockResolvedValueOnce(undefined);
    const { onSaved } = renderEditor({ selectedHost: "h1", node: { id: "h1" } as TopologyNode });
    const select = screen.getByLabelText(/^Host criticality/) as HTMLSelectElement;

    await act(async () => {
      fireEvent.change(select, { target: { value: "high" } });
    });

    expect(checkmkWrite.setCriticality).toHaveBeenCalledWith("h1", "high");
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(select.value).toBe("high");
  });

  it("a failed Host criticality write calls onFailed and reverts the optimistic value", async () => {
    vi.mocked(checkmkWrite.setCriticality).mockRejectedValueOnce(new Error("rejected"));
    const { onFailed } = renderEditor({ selectedHost: "h1", node: { id: "h1" } as TopologyNode });
    const select = screen.getByLabelText(/^Host criticality/) as HTMLSelectElement;

    await act(async () => {
      fireEvent.change(select, { target: { value: "high" } });
    });

    await waitFor(() =>
      expect(onFailed).toHaveBeenCalledWith({
        title: "Couldn't save that",
        body: "Checkmk rejected the update. Check that the device still exists, then try again.",
      }),
    );
    expect(select.value).toBe("low");
  });

  it("lists services from props union existing service_criticality keys, sorted", () => {
    renderEditor({
      selectedHost: "h1",
      node: { id: "h1", service_criticality: { sshd: "high" } } as unknown as TopologyNode,
      serviceNames: ["cron"],
    });
    expect(screen.getByText("cron")).toBeInTheDocument();
    expect(screen.getByText("sshd")).toBeInTheDocument();
  });

  it("choosing Default on a service row calls setServiceCriticality with a null tier", async () => {
    vi.mocked(checkmkWrite.setServiceCriticality).mockResolvedValueOnce(undefined);
    renderEditor({
      selectedHost: "h1",
      node: { id: "h1", service_criticality: { sshd: "high" } } as unknown as TopologyNode,
      serviceNames: [],
    });
    const select = screen.getByRole("combobox", { name: "sshd" }) as HTMLSelectElement;
    expect(select.value).toBe("high");

    await act(async () => {
      fireEvent.change(select, { target: { value: "default" } });
    });

    expect(checkmkWrite.setServiceCriticality).toHaveBeenCalledWith("h1", "sshd", null);
  });

  it("Depends-on lists every other topology host id, never the selected host", () => {
    renderEditor({ selectedHost: "h1", node: { id: "h1" } as TopologyNode });
    fireEvent.click(screen.getByRole("button", { name: "Search devices…" }));
    expect(screen.getByRole("checkbox", { name: "h2" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "h3" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "h1" })).not.toBeInTheDocument();
  });

  it("adding a dependency calls updateDependsOn with a mutate returning the new list", async () => {
    vi.mocked(checkmkWrite.updateDependsOn).mockResolvedValueOnce(undefined);
    const { onSaved } = renderEditor({
      selectedHost: "h1",
      node: { id: "h1", depends_on: ["h2"] } as unknown as TopologyNode,
    });
    fireEvent.click(screen.getByRole("button", { name: "h2" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "h3" }));
    });

    expect(checkmkWrite.updateDependsOn).toHaveBeenCalledWith("h1", expect.any(Function));
    const mutate = vi.mocked(checkmkWrite.updateDependsOn).mock.calls[0][1];
    expect(mutate([])).toEqual(["h2", "h3"]);
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  });

  it("removing a dependency confirms with the exact UI-SPEC text, and a cancelled confirm makes no write and keeps it selected", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderEditor({
      selectedHost: "h1",
      node: { id: "h1", depends_on: ["h2"] } as unknown as TopologyNode,
    });
    fireEvent.click(screen.getByRole("button", { name: "h2" }));
    const checkbox = screen.getByRole("checkbox", { name: "h2" }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);

    fireEvent.click(checkbox);

    expect(confirmSpy).toHaveBeenCalledWith(
      "Remove this dependency?\n\nh1 will no longer be counted as affected by h2's incidents. This won't take effect until you press Apply changes.",
    );
    expect(checkmkWrite.updateDependsOn).not.toHaveBeenCalled();
    expect(checkbox.checked).toBe(true);
    confirmSpy.mockRestore();
  });

  it("a confirmed dependency removal writes the empty result", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(checkmkWrite.updateDependsOn).mockResolvedValueOnce(undefined);
    renderEditor({
      selectedHost: "h1",
      node: { id: "h1", depends_on: ["h2"] } as unknown as TopologyNode,
    });
    fireEvent.click(screen.getByRole("button", { name: "h2" }));
    const checkbox = screen.getByRole("checkbox", { name: "h2" });

    await act(async () => {
      fireEvent.click(checkbox);
    });

    expect(checkmkWrite.updateDependsOn).toHaveBeenCalledWith("h1", expect.any(Function));
    const mutate = vi.mocked(checkmkWrite.updateDependsOn).mock.calls[0][1];
    expect(mutate(["h2"])).toEqual([]);
    confirmSpy.mockRestore();
  });
});
