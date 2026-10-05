import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlertsPane, AlertsSummary } from "./AlertsPane";
import type { Incident } from "../lib/incidents";
import type { NeedPayload, NeedTier } from "../lib/types";

const STORAGE_KEY = "dashboard-react.alertsTab.v1";

function incident(overrides: Partial<Incident> & { id: string; root: string }): Incident {
  return {
    rootState: "DOWN",
    inferred: false,
    confirmedDown: [],
    notObservable: [],
    dependents: [],
    worstCriticality: "low",
    since: null,
    ...overrides,
  };
}

function need(id: string, tier: NeedTier): NeedPayload {
  return {
    id,
    source: "trend",
    host: "srv-a",
    service: "Filesystem /",
    metric: "fs_used_percent",
    unit: "%",
    tier,
    computed_tier: tier,
    days_to_warn: 10,
    days_to_crit: 30,
    warn_date: "",
    crit_date: "",
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
    generated_at: "",
  };
}

function renderPane(props: Partial<React.ComponentProps<typeof AlertsPane>> = {}) {
  const defaults: React.ComponentProps<typeof AlertsPane> = {
    incidentsPanel: <div>incidents-body</div>,
    needsPanel: <div>needs-body</div>,
    incidentCount: 2,
    needCount: 5,
    editMode: false,
  };
  return render(<AlertsPane {...defaults} {...props} />);
}

const incidentsTab = () => screen.getByRole("tab", { name: /^Incidents/ });
const needsTab = () => screen.getByRole("tab", { name: /^Needs/ });

describe("AlertsPane", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("renders a labelled tablist with a count in each tab name, Incidents selected by default", () => {
    renderPane();
    expect(screen.getByRole("tablist", { name: "Incidents and needs" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Incidents 2" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Needs 5" })).toHaveAttribute("aria-selected", "false");
  });

  it("links each tab to its tabpanel via aria-controls and aria-labelledby", () => {
    renderPane();
    const tab = incidentsTab();
    const panel = document.getElementById(tab.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("role", "tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", tab.id);
  });

  it("swaps the visible panel on click and keeps the other panel mounted but hidden", () => {
    renderPane();
    expect(screen.getByText("incidents-body")).toBeVisible();
    fireEvent.click(needsTab());
    expect(screen.getByText("needs-body")).toBeVisible();
    expect(screen.getByText("incidents-body")).not.toBeVisible();
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves selection with the arrow keys (wrapping), Home and End, with roving tabIndex", () => {
    renderPane();
    expect(incidentsTab()).toHaveAttribute("tabindex", "0");
    expect(needsTab()).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(incidentsTab(), { key: "ArrowRight" });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
    expect(needsTab()).toHaveFocus();
    fireEvent.keyDown(needsTab(), { key: "ArrowRight" });
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(incidentsTab(), { key: "ArrowLeft" });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(needsTab(), { key: "Home" });
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(incidentsTab(), { key: "End" });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("persists the selected tab and restores it on the next mount", () => {
    const first = renderPane();
    fireEvent.click(needsTab());
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toBe("needs");
    first.unmount();
    renderPane();
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to Incidents for a corrupt stored value", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify("bogus"));
    renderPane();
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to Incidents when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderPane();
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("in edit mode disables Incidents, forces Needs, and restores the previous tab afterwards", () => {
    const { rerender } = renderPane();
    const props: React.ComponentProps<typeof AlertsPane> = {
      incidentsPanel: <div>incidents-body</div>,
      needsPanel: <div>needs-body</div>,
      incidentCount: 2,
      needCount: 5,
      editMode: true,
    };
    rerender(<AlertsPane {...props} />);
    expect(incidentsTab()).toBeDisabled();
    expect(incidentsTab()).toHaveAttribute("title", "Unavailable in topology edit mode");
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("needs-body")).toBeVisible();
    fireEvent.click(incidentsTab());
    fireEvent.keyDown(needsTab(), { key: "ArrowLeft" });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
    // The stored choice is untouched by edit mode.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    rerender(<AlertsPane {...props} editMode={false} />);
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("incidents-body")).toBeVisible();
  });

  it("selects and persists Incidents when focusIncidentId becomes set", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify("needs"));
    const { rerender } = renderPane({ focusIncidentId: null });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
    rerender(
      <AlertsPane
        incidentsPanel={<div>incidents-body</div>}
        needsPanel={<div>needs-body</div>}
        incidentCount={2}
        needCount={5}
        editMode={false}
        focusIncidentId="incident-x"
      />,
    );
    expect(incidentsTab()).toHaveAttribute("aria-selected", "true");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toBe("incidents");
  });

  it("does not switch tabs for an empty focusIncidentId", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify("needs"));
    renderPane({ focusIncidentId: "" });
    expect(needsTab()).toHaveAttribute("aria-selected", "true");
  });
});

describe("AlertsSummary", () => {
  const down = incident({ id: "d", root: "d", confirmedDown: ["x"] });
  const unreach = incident({ id: "w", root: "w", rootState: "UNREACH" });

  it("renders quiet text when nothing is open", () => {
    render(<AlertsSummary incidents={[]} needs={[]} />);
    expect(screen.getByText("No open incidents or needs")).toBeInTheDocument();
    expect(screen.queryByTestId("alerts-severity")).toBeNull();
  });

  it("shows the combined count and ranks a danger incident above everything", () => {
    render(<AlertsSummary incidents={[unreach, down]} needs={[need("a", "immediate")]} />);
    const summary = screen.getByTestId("alerts-severity");
    expect(summary).toHaveAttribute("data-severity", "danger");
    expect(summary).toHaveTextContent("3");
    expect(summary).toHaveAttribute("aria-label", "2 open incidents, 1 service need");
  });

  it("is warning for a warning incident or an immediate need", () => {
    const { rerender } = render(<AlertsSummary incidents={[unreach]} needs={[]} />);
    expect(screen.getByTestId("alerts-severity")).toHaveAttribute("data-severity", "warning");
    rerender(<AlertsSummary incidents={[]} needs={[need("a", "standard"), need("b", "immediate")]} />);
    expect(screen.getByTestId("alerts-severity")).toHaveAttribute("data-severity", "warning");
  });

  it("falls through urgent then standard needs", () => {
    const { rerender } = render(<AlertsSummary incidents={[]} needs={[need("a", "urgent")]} />);
    expect(screen.getByTestId("alerts-severity")).toHaveAttribute("data-severity", "urgent");
    rerender(<AlertsSummary incidents={[]} needs={[need("a", "standard")]} />);
    expect(screen.getByTestId("alerts-severity")).toHaveAttribute("data-severity", "standard");
  });
});
