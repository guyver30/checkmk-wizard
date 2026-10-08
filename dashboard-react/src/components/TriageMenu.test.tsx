import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TRIAGE_CHECK_MS, TriageMenu } from "./TriageMenu";
import { useAppStore } from "../store/useAppStore";
import type { TriageCommand } from "../lib/triageMode";
import type { NeedPayload } from "../lib/types";

const INITIAL_STATE = useAppStore.getState();

function need(overrides: Partial<NeedPayload> = {}): NeedPayload {
  return {
    id: "n1",
    source: "trend",
    host: "srv-a",
    service: "Filesystem /",
    metric: "fs_used_percent",
    unit: "%",
    tier: "urgent",
    computed_tier: "urgent",
    days_to_warn: 10,
    days_to_crit: 30,
    warn_date: null,
    crit_date: null,
    confidence: "high",
    history_days: 21,
    value: 70,
    warn: 80,
    crit: 90,
    sustained_fraction: null,
    window_hours: null,
    since: "",
    narration: "",
    triage: null,
    generated_at: "2026-10-04T12:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

afterEach(() => {
  vi.useRealTimers();
});

function open(publish = vi.fn(async (_cmd: TriageCommand) => true), n = need()) {
  render(<TriageMenu need={n} hostLabel="Server A" publish={publish} />);
  fireEvent.click(screen.getByRole("button", { name: "Triage" }));
  return publish;
}

describe("TriageMenu", () => {
  it("lists the three items", () => {
    open();
    expect(screen.getByRole("menuitem", { name: "Downgrade" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Upgrade to immediate" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Cancel need" })).toBeEnabled();
  });

  it("disables Downgrade at standard and Upgrade at immediate", () => {
    const { unmount } = render(<TriageMenu need={need({ tier: "standard" })} hostLabel="h" publish={vi.fn(async () => true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Triage" }));
    expect(screen.getByRole("menuitem", { name: "Downgrade" })).toBeDisabled();
    fireEvent.mouseEnter(screen.getByRole("menuitem", { name: "Downgrade" }).parentElement as HTMLElement);
    expect(screen.getByText("Already standard")).toBeInTheDocument();
    unmount();
    render(<TriageMenu need={need({ tier: "immediate" })} hostLabel="h" publish={vi.fn(async () => true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Triage" }));
    expect(screen.getByRole("menuitem", { name: "Upgrade to immediate" })).toBeDisabled();
    fireEvent.mouseEnter(screen.getByRole("menuitem", { name: "Upgrade to immediate" }).parentElement as HTMLElement);
    expect(screen.getByText("Already immediate")).toBeInTheDocument();
  });

  it("downgrade publishes immediately and shows the Sent snackbar", async () => {
    const publish = open();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Downgrade" }));
    });
    expect(publish).toHaveBeenCalledTimes(1);
    expect(publish.mock.calls[0][0]).toMatchObject({ need_id: "n1", action: "downgrade" });
    expect(screen.getByText("Sent: downgrade for Server A, Filesystem / · fs_used_percent")).toBeInTheDocument();
  });

  it("cancel need publishes only after confirming, with the typed reason as note", async () => {
    const publish = open();
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancel need" }));
    expect(publish).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Cancel this need?");
    expect(dialog).toHaveTextContent(
      "Server A, Filesystem / · fs_used_percent will be hidden from the Service needs pane until it resolves and comes back. The action is recorded.",
    );
    expect(screen.getByRole("button", { name: "Keep need" })).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Reason (optional)"), { target: { value: "planned work" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel need" }));
    });
    expect(publish).toHaveBeenCalledTimes(1);
    expect(publish.mock.calls[0][0]).toMatchObject({ action: "cancel", note: "planned work" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Keep need and Escape close the dialog without publishing", () => {
    const publish = open();
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancel need" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep need" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Triage" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancel need" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(publish).not.toHaveBeenCalled();
  });

  it("shows the persistent error when the need does not change within 15 s", async () => {
    vi.useFakeTimers();
    useAppStore.setState({ needs: { n1: need() } });
    open();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Downgrade" }));
    });
    expect(screen.queryByText(/Could not apply/)).toBeNull();
    act(() => {
      vi.advanceTimersByTime(TRIAGE_CHECK_MS + 1);
    });
    expect(
      screen.getByText(
        "Could not apply: no update received from the analytics service. Nothing changed. Try again in a few seconds.",
      ),
    ).toBeInTheDocument();
  });

  it("shows no error when the republished need carries a new triage", async () => {
    vi.useFakeTimers();
    useAppStore.setState({ needs: { n1: need() } });
    open();
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Downgrade" }));
    });
    useAppStore.setState({
      needs: {
        n1: need({
          tier: "standard",
          triage: {
            action: "downgrade",
            tier: "standard",
            set_at: "2026-10-04T12:01:00Z",
            computed_tier_at_set: "urgent",
            note: "",
            by: "",
          },
        }),
      },
    });
    act(() => {
      vi.advanceTimersByTime(TRIAGE_CHECK_MS + 1);
    });
    expect(screen.queryByText(/Could not apply/)).toBeNull();
  });

  it("shows the login-unavailable message when publishing fails", async () => {
    open(vi.fn(async (_cmd: TriageCommand) => false));
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Downgrade" }));
    });
    expect(
      screen.getAllByText(
        "Triage login unavailable. Reload the page, or check the dashboard container configuration.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("stays clickable after a failed send and reopening clears the failure state", async () => {
    // IN-02: one failed send used to disable Triage for that row until a page reload.
    const publish = open(vi.fn(async (_cmd: TriageCommand) => false));
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Downgrade" }));
    });
    const trigger = screen.getByRole("button", { name: "Triage" });
    expect(trigger).not.toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(
      screen.queryAllByText(
        "Triage login unavailable. Reload the page, or check the dashboard container configuration.",
      ),
    ).toHaveLength(0);
    expect(publish).toHaveBeenCalledTimes(1);
  });
});
