import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EventHistory } from "./EventHistory";
import { useAppStore } from "../store/useAppStore";
import type { EventEntry } from "../lib/types";

// Same reset pattern as useAppStore.test.ts / IndexRoute.test.tsx: a snapshot of the store's
// initial state, replaced wholesale between tests via the test-only `true` argument.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

function oldestFirstEvents(): EventEntry[] {
  return [
    { device_id: "a", from: "OK", to: "WARN", timestamp: "2026-01-01T00:00:00Z" },
    { device_id: "b", from: "OK", to: "CRIT", timestamp: "2026-01-01T00:01:00Z" },
    { device_id: "c", from: "WARN", to: "OK", timestamp: "2026-01-01T00:02:00Z" },
  ];
}

describe("EventHistory", () => {
  it("renders the full events list newest-first from an oldest-first store array", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    const log = screen.getByRole("log", { name: /recent events/i });
    const labels = within(log)
      .getAllByText(/^[abc]$/)
      .map((el) => el.textContent);
    expect(labels).toEqual(["c", "b", "a"]);
  });

  it("does not mutate the store's events array while rendering", () => {
    const events = oldestFirstEvents();
    useAppStore.setState({ events });
    render(<EventHistory />);
    expect(useAppStore.getState().events.map((entry) => entry.device_id)).toEqual(["a", "b", "c"]);
  });

  it("renders an explicit empty state for an empty events array", () => {
    useAppStore.setState({ events: [] });
    render(<EventHistory />);
    expect(screen.getByText(/no recent events/i)).toBeInTheDocument();
  });

  it("renders the raw device_id when the device is absent from the store", () => {
    useAppStore.setState({
      events: [{ device_id: "unknown-host", from: "OK", to: "DOWN", timestamp: "2026-01-01T00:00:00Z" }],
    });
    render(<EventHistory />);
    expect(screen.getByText("unknown-host")).toBeInTheDocument();
  });

  it("renders without throwing when an entry is null, and still renders sibling rows", () => {
    useAppStore.setState({
      events: [
        { device_id: "a", from: "OK", to: "WARN", timestamp: "2026-01-01T00:00:00Z" },
        null as unknown as EventEntry,
        { device_id: "c", from: "WARN", to: "OK", timestamp: "2026-01-01T00:02:00Z" },
      ],
    });
    expect(() => render(<EventHistory />)).not.toThrow();
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("c")).toBeInTheDocument();
  });

  it("puts a newly pushed event at the top after handleMessage delivers a fresh snapshot", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);

    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/events/recent",
          encode([
            ...oldestFirstEvents(),
            { device_id: "d", from: "OK", to: "WARN", timestamp: "2026-01-01T00:03:00Z" },
          ]),
        );
    });

    const log = screen.getByRole("log", { name: /recent events/i });
    const labels = within(log)
      .getAllByText(/^[abcd]$/)
      .map((el) => el.textContent);
    expect(labels[0]).toBe("d");
  });

  it("exposes the pane via role=log with an accessible name", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    expect(screen.getByRole("log", { name: /recent events/i })).toBeInTheDocument();
  });
});
