import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { IncidentList } from "./IncidentList";
import type { Incident } from "../lib/incidents";
import type { DevicePayload } from "../lib/types";

const NOW_MS = Date.parse("2026-09-26T12:00:00Z");

function incident(overrides: Partial<Incident> & { id: string; root: string }): Incident {
  return {
    rootState: "DOWN",
    inferred: false,
    confirmedDown: [],
    notObservable: [],
    dependents: [],
    worstCriticality: "low",
    since: NOW_MS ? new Date(NOW_MS - 5 * 60 * 1000).toISOString() : null,
    ...overrides,
  };
}

function renderList(props: Partial<React.ComponentProps<typeof IncidentList>> = {}) {
  const defaults: React.ComponentProps<typeof IncidentList> = {
    incidents: [],
    devices: {},
    nowMs: NOW_MS,
  };
  return render(
    <MemoryRouter>
      <IncidentList {...defaults} {...props} />
    </MemoryRouter>,
  );
}

describe("IncidentList", () => {
  it("renders one card per incident, in the order given (critical first)", () => {
    const older = incident({
      id: "incident-sw-edge-a",
      root: "sw-edge-a",
      worstCriticality: "high",
      since: new Date(NOW_MS - 60 * 60 * 1000).toISOString(),
    });
    const newer = incident({
      id: "incident-sw-edge-b",
      root: "sw-edge-b",
      worstCriticality: "critical",
      since: new Date(NOW_MS - 5 * 60 * 1000).toISOString(),
    });
    renderList({ incidents: [newer, older] });

    const cards = screen.getByRole("region", { name: /open incidents/i }).querySelectorAll("[data-incident-id]");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute("data-incident-id", "incident-sw-edge-b");
    expect(cards[1]).toHaveAttribute("data-incident-id", "incident-sw-edge-a");
  });

  it("card title reads '{rootLabel} — {duration}', falling back to the root id when no alias", () => {
    const inc = incident({
      id: "incident-sw-edge-b",
      root: "sw-edge-b",
      since: new Date(NOW_MS - 12 * 60 * 1000).toISOString(),
    });
    renderList({ incidents: [inc] });
    expect(screen.getByText("sw-edge-b — 12 min")).toBeInTheDocument();
  });

  it("uses the device's alias as rootLabel when present", () => {
    const inc = incident({ id: "incident-h1", root: "h1" });
    const devices: Record<string, DevicePayload> = { h1: { id: "h1", alias: "Tower B switch" } };
    renderList({ incidents: [inc], devices });
    expect(screen.getByText(/Tower B switch —/)).toBeInTheDocument();
  });

  it("shows the 'Inferred, not confirmed' badge only when inferred is true", () => {
    const inferred = incident({ id: "incident-a", root: "a", inferred: true });
    const { rerender } = render(
      <MemoryRouter>
        <IncidentList incidents={[inferred]} devices={{}} nowMs={NOW_MS} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Inferred, not confirmed")).toBeInTheDocument();

    const notInferred = incident({ id: "incident-b", root: "b", inferred: false });
    rerender(
      <MemoryRouter>
        <IncidentList incidents={[notInferred]} devices={{}} nowMs={NOW_MS} />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Inferred, not confirmed")).not.toBeInTheDocument();
  });

  it("renders the consequence summary text and the criticality badge with the tier name", () => {
    const inc = incident({
      id: "incident-a",
      root: "a",
      confirmedDown: ["c1", "c2"],
      notObservable: ["n1"],
      worstCriticality: "critical",
    });
    renderList({ incidents: [inc] });
    expect(screen.getByText("2 confirmed down · 1 not observable")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("renders status='danger' when there is a confirmed-down consequence", () => {
    const inc = incident({ id: "incident-a", root: "a", confirmedDown: ["c1"] });
    renderList({ incidents: [inc] });
    expect(screen.getByRole("region").querySelector('[data-incident-id="incident-a"]')).toHaveAttribute(
      "data-status",
      "danger",
    );
  });

  it("renders status='warning' when the incident is all-not-observable or inferred", () => {
    const inc = incident({ id: "incident-a", root: "a", notObservable: ["n1"], inferred: true });
    renderList({ incidents: [inc] });
    expect(screen.getByRole("region").querySelector('[data-incident-id="incident-a"]')).toHaveAttribute(
      "data-status",
      "warning",
    );
  });

  it("'View devices' toggles an inline list: headings only for non-empty groups, hosts link to /details, and a dependents line only when non-empty", () => {
    const inc = incident({
      id: "incident-a",
      root: "a",
      confirmedDown: ["c1"],
      notObservable: [],
      dependents: ["dep1", "dep2"],
    });
    const devices: Record<string, DevicePayload> = {
      c1: { id: "c1", alias: "Confirmed Device" },
      dep1: { id: "dep1" },
      dep2: { id: "dep2" },
    };
    renderList({ incidents: [inc], devices });

    expect(screen.queryByText("Confirmed down")).not.toBeInTheDocument();
    expect(screen.queryByText("Not observable")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View devices" }));

    expect(screen.getByText("Confirmed down")).toBeInTheDocument();
    expect(screen.queryByText("Not observable")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Confirmed Device" });
    expect(link).toHaveAttribute("href", "/details?id=c1");
    expect(screen.getByText("Dependent devices: dep1, dep2")).toBeInTheDocument();
  });

  it("renders nothing for the consequence-summary line when the incident has no counts", () => {
    const inc = incident({ id: "incident-a", root: "a", confirmedDown: [], notObservable: [] });
    renderList({ incidents: [inc] });
    expect(screen.queryByText(/confirmed down/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not observable/)).not.toBeInTheDocument();
  });

  it("empty list renders 'No open incidents' and the body copy, with no Message card", () => {
    renderList({ incidents: [] });
    expect(screen.getByText("No open incidents")).toBeInTheDocument();
    expect(
      screen.getByText("Every device the poller can reach is reporting normally."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /open incidents/i })).not.toBeInTheDocument();
  });

  it("highlightedId matching a card adds a ring class and scrolls it into view once", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    const a = incident({ id: "incident-a", root: "a" });
    const b = incident({ id: "incident-b", root: "b" });
    renderList({ incidents: [a, b], highlightedId: "incident-b" });

    const highlighted = screen.getByRole("region").querySelector('[data-incident-id="incident-b"]');
    expect(highlighted).toHaveClass("ring-2");
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    const notHighlighted = screen.getByRole("region").querySelector('[data-incident-id="incident-a"]');
    expect(notHighlighted).not.toHaveClass("ring-2");
  });

  it("never renders the words 'not operating' anywhere in the list", () => {
    const inc = incident({
      id: "incident-a",
      root: "a",
      inferred: true,
      confirmedDown: ["c1"],
      notObservable: ["n1"],
      dependents: ["d1"],
    });
    renderList({ incidents: [inc] });
    fireEvent.click(screen.getByRole("button", { name: "View devices" }));
    expect(document.body.textContent).not.toMatch(/not operating/i);
  });
});
