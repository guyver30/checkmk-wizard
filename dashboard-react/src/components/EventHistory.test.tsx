import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

// Local datetime-local value / display string built from local getters so tests are TZ-independent.
const pad = (n: number) => String(n).padStart(2, "0");
function toInputValue(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function toDisplay(iso: string): string {
  const d = new Date(iso);
  return `${toInputValue(iso).replace("T", " ")}:${pad(d.getSeconds())}`;
}
function rowIds(): (string | null)[] {
  const log = screen.getByRole("log", { name: /recent events/i });
  return within(log)
    .queryAllByText(/^[abc]$/)
    .map((el) => el.textContent);
}

describe("EventHistory date+time and range filter", () => {
  it("shows the full local date and time on every row inside a <time> element", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    const first = oldestFirstEvents()[2].timestamp as string;
    const el = screen.getByText(toDisplay(first));
    expect(el.tagName).toBe("TIME");
    expect(el).toHaveAttribute("datetime", first);
  });

  it("renders From/To datetime-local inputs and a Clear button", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    expect(screen.getByLabelText(/from/i)).toHaveAttribute("type", "datetime-local");
    expect(screen.getByLabelText(/to/i)).toHaveAttribute("type", "datetime-local");
    expect(screen.getByRole("button", { name: /clear/i })).toBeDisabled();
  });

  it("From hides older rows and keeps newest-first order", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    fireEvent.change(screen.getByLabelText(/from/i), {
      target: { value: toInputValue("2026-01-01T00:01:00Z") },
    });
    expect(rowIds()).toEqual(["c", "b"]);
  });

  it("shows 'No events in this range' when nothing matches", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    fireEvent.change(screen.getByLabelText(/from/i), { target: { value: "2030-01-01T00:00" } });
    expect(screen.getByText(/no events in this range/i)).toBeInTheDocument();
    expect(screen.queryByText(/no recent events/i)).not.toBeInTheDocument();
    expect(screen.getByRole("log", { name: /recent events/i })).toBeInTheDocument();
  });

  it("shows an inline error and leaves rows unfiltered for a reversed range", () => {
    useAppStore.setState({ events: oldestFirstEvents() });
    render(<EventHistory />);
    fireEvent.change(screen.getByLabelText(/from/i), { target: { value: "2030-01-01T00:00" } });
    fireEvent.change(screen.getByLabelText(/to/i), { target: { value: "2020-01-01T00:00" } });
    expect(screen.getByText(/end must be after start/i)).toBeInTheDocument();
    expect(rowIds()).toEqual(["c", "b", "a"]);
  });

  it("Clear resets both inputs and restores all rows, without mutating the store array", () => {
    const events = oldestFirstEvents();
    useAppStore.setState({ events });
    render(<EventHistory />);
    const from = screen.getByLabelText(/from/i) as HTMLInputElement;
    fireEvent.change(from, { target: { value: toInputValue("2026-01-01T00:02:00Z") } });
    expect(rowIds()).toEqual(["c"]);
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(from.value).toBe("");
    expect(rowIds()).toEqual(["c", "b", "a"]);
    expect(useAppStore.getState().events.map((e) => e.device_id)).toEqual(["a", "b", "c"]);
  });

  it("keeps 'No recent events' when the store is empty", () => {
    useAppStore.setState({ events: [] });
    render(<EventHistory />);
    fireEvent.change(screen.getByLabelText(/from/i), { target: { value: "2030-01-01T00:00" } });
    expect(screen.getByText(/no recent events/i)).toBeInTheDocument();
  });
});
