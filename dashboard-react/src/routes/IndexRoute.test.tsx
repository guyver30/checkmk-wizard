import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
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
  it("renders the stats strip before the topology map, in document order", () => {
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    const status = screen.getByRole("status", { name: /fleet state summary/i });
    const map = screen.getByTestId("topology-map");
    // DOCUMENT_POSITION_FOLLOWING (4) set on `map` relative to `status` means status comes
    // first in document order.
    const position = status.compareDocumentPosition(map);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("updates the strip's counts in place without remounting the topology map", () => {
    render(
      <MemoryRouter>
        <IndexRoute />
      </MemoryRouter>,
    );
    const mapBefore = screen.getByTestId("topology-map");

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
    const mapAfter = screen.getByTestId("topology-map");
    expect(mapAfter).toBe(mapBefore);
  });
});
