import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TopologyToolbar } from "./TopologyToolbar";

function renderToolbar(overrides: Partial<Parameters<typeof TopologyToolbar>[0]> = {}) {
  const onEditModeChange = vi.fn();
  const onApply = vi.fn();
  const props = {
    editMode: false,
    onEditModeChange,
    pendingCount: 0,
    applying: false,
    onApply,
    editingConfigured: true,
    ...overrides,
  };
  const result = render(<TopologyToolbar {...props} />);
  return { ...result, onEditModeChange, onApply };
}

describe("TopologyToolbar", () => {
  it("with editMode false renders only an unchecked switch, no Banner or Apply button", () => {
    renderToolbar({ editMode: false });
    const toggle = screen.getByRole("switch", { name: "Edit topology" });
    expect(toggle).toBeInTheDocument();
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply changes/i })).not.toBeInTheDocument();
  });

  it("with editMode true and pendingCount 0, Apply is disabled and no Banner is shown", () => {
    renderToolbar({ editMode: true, pendingCount: 0 });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const applyButton = screen.getByRole("button", { name: "Apply changes" });
    expect(applyButton).toBeDisabled();
  });

  it("pendingCount 1 shows singular Banner text and enables Apply with variant primary", () => {
    renderToolbar({ editMode: true, pendingCount: 1 });
    expect(screen.getByRole("alert")).toHaveTextContent("1 change not yet applied");
    const applyButton = screen.getByRole("button", { name: "Apply changes" });
    expect(applyButton).toBeEnabled();
  });

  it("pendingCount 3 shows plural Banner text", () => {
    renderToolbar({ editMode: true, pendingCount: 3 });
    expect(screen.getByRole("alert")).toHaveTextContent("3 changes not yet applied");
  });

  it("applying true shows 'Applying…' and is in loading state", () => {
    renderToolbar({ editMode: true, pendingCount: 2, applying: true });
    const applyButton = screen.getByRole("button", { name: "Applying…" });
    expect(applyButton).toBeDisabled();
  });

  it("toggling the switch calls onEditModeChange(!editMode)", async () => {
    const user = userEvent.setup();
    const { onEditModeChange } = renderToolbar({ editMode: false });
    await user.click(screen.getByRole("switch", { name: "Edit topology" }));
    expect(onEditModeChange).toHaveBeenCalledWith(true);
  });

  it("clicking Apply calls onApply once", async () => {
    const user = userEvent.setup();
    const { onApply } = renderToolbar({ editMode: true, pendingCount: 1 });
    await user.click(screen.getByRole("button", { name: "Apply changes" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("editingConfigured false disables the switch and shows the configuration hint", () => {
    renderToolbar({ editMode: false, editingConfigured: false });
    const toggle = screen.getByRole("switch", { name: "Edit topology" });
    expect(toggle).toBeDisabled();
    expect(
      screen.getByText("Editing is off until TOPOLOGY_EDITOR_SECRET is set in src/lib/config.ts."),
    ).toBeInTheDocument();
  });
});
