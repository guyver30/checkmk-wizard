import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { IndexRoute } from "./IndexRoute";
import { useAppStore } from "../store/useAppStore";

// Same reset pattern as useAppStore.test.ts: a snapshot of the store's initial state, replaced
// wholesale between tests via the test-only `true` argument.
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

describe("IndexRoute", () => {
  it("renders the stats strip before the map placeholder, in document order", () => {
    render(<IndexRoute />);
    const status = screen.getByRole("status", { name: /fleet state summary/i });
    const placeholder = screen.getByText("Topology map — Phase 13");
    // DOCUMENT_POSITION_FOLLOWING (4) set on `placeholder` relative to `status` means status
    // comes first in document order.
    const position = status.compareDocumentPosition(placeholder);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("updates the strip's counts in place without remounting the map placeholder", () => {
    render(<IndexRoute />);
    const placeholderBefore = screen.getByText("Topology map — Phase 13");

    act(() => {
      useAppStore
        .getState()
        .handleMessage(
          "lan/devices/h1/status",
          encode({ id: "h1", state: "DOWN", timestamp: new Date().toISOString() }),
        );
    });

    const status = screen.getByRole("status", { name: /fleet state summary/i });
    expect(within(status).getByText("DOWN")).toBeInTheDocument();
    const placeholderAfter = screen.getByText("Topology map — Phase 13");
    expect(placeholderAfter).toBe(placeholderBefore);
  });
});
