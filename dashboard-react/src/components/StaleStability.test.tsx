// D-34 regression: a stale flip caused purely by elapsed time must be VISUAL-ONLY -- it must
// not discard scroll position, keyboard focus, or tree-expand state, and it must not remount
// any DOM subtree the flip did not touch. Named for the requirement, not a component, so its
// purpose survives a refactor (D-43 names this file explicitly).
//
// If any assertion here fails, the fix is to make the render path stable -- stable React
// keys, no conditional remount of a parent, no key derived from a value that changes on the
// flip -- never to weaken the assertion. These assertions exist precisely because D-43
// refuses to let React's reconciler be assumed to handle this "for free": they are checked
// against React's actual re-render behavior via captured DOM node references (`toBe`), not
// assumed from the framework's reputation.

import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndexRoute } from "../routes/IndexRoute";
import { useAppStore } from "../store/useAppStore";
import { CLOCK_TICK_MS } from "../hooks/useNowTick";
import { POLL_INTERVAL_SECONDS, STALENESS_FACTOR } from "../lib/config";

const INITIAL_STATE = useAppStore.getState();

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

const START_TIME = new Date("2026-01-01T00:00:00.000Z");

// The staleness threshold in ms, rounded up to the next whole CLOCK_TICK_MS multiple (plus
// one extra tick of margin) so the fake timer's setInterval is guaranteed to actually cross
// it -- a threshold landing strictly between two ticks would never fire the tick that flips
// the badge.
const THRESHOLD_MS = STALENESS_FACTOR * POLL_INTERVAL_SECONDS * 1000;
const ADVANCE_MS = (Math.ceil(THRESHOLD_MS / CLOCK_TICK_MS) + 1) * CLOCK_TICK_MS;

function seedStore() {
  useAppStore.getState().handleMessage(
    "lan/devices/front-door/status",
    encode({
      id: "front-door",
      device_type: "camera",
      state: "OK",
      timestamp: START_TIME.toISOString(),
      // No `staleness` field -- ages out via the timestamp fallback (D-17), which is
      // exactly the path this test needs to exercise.
    }),
  );
  useAppStore.getState().handleMessage(
    "lan/devices/hallway/status",
    encode({
      id: "hallway",
      device_type: "sensor",
      state: "OK",
      timestamp: START_TIME.toISOString(),
      // Checkmk's own authoritative staleness value (D-17) pins this device fresh
      // regardless of elapsed time -- this group is the test's control: nothing about it
      // is expected to change when the clock advances.
      staleness: 0,
    }),
  );
}

describe("StaleStability (D-34)", () => {
  beforeEach(() => {
    useAppStore.setState(INITIAL_STATE, true);
    vi.useFakeTimers();
    vi.setSystemTime(START_TIME);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("flips a device to STALE purely from elapsed time, with no other UI state lost", async () => {
    act(() => {
      seedStore();
    });

    render(<IndexRoute />);

    // Expand both groups.
    await act(async () => {
      screen.getByRole("button", { name: /camera/i }).click();
      screen.getByRole("button", { name: /sensor/i }).click();
    });

    const cameraGroupRowBefore = screen.getByRole("treeitem", { name: /camera/i });
    const sensorGroupRowBefore = screen.getByRole("treeitem", { name: /sensor/i });
    const mapPlaceholderBefore = screen.getByText("Topology map — Phase 13");

    // Focus the camera group's own toggle button -- the group about to flip.
    const cameraButton = screen.getByRole("button", { name: /camera/i });
    cameraButton.focus();
    expect(document.activeElement).toBe(cameraButton);

    // Scroll the event log. jsdom has no real layout/scrolling engine, so this mirrors
    // exactly what dashboard/js/render-shell.js's own tick() reads/writes: `el.scrollTop`
    // directly, never scrollTo()/scrollIntoView().
    const eventLog = screen.getByRole("log", { name: /recent events/i });
    eventLog.scrollTop = 42;
    expect(eventLog.scrollTop).toBe(42);

    // Advance the clock past the staleness threshold, purely by elapsed time -- deliberately
    // dispatching NO MQTT message during the flip.
    await act(async () => {
      vi.advanceTimersByTime(ADVANCE_MS);
    });

    // 1. The camera device flipped to STALE.
    const cameraGroupRowAfter = screen.getByRole("treeitem", { name: /camera/i });
    expect(within(cameraGroupRowAfter).getByText("STALE")).toBeInTheDocument();

    // 2. Both groups are still expanded.
    expect(cameraGroupRowAfter).toHaveAttribute("aria-expanded", "true");
    const sensorGroupRowAfter = screen.getByRole("treeitem", { name: /sensor/i });
    expect(sensorGroupRowAfter).toHaveAttribute("aria-expanded", "true");

    // 3. The unaffected (sensor) group's row is the SAME DOM node object -- no remount.
    expect(sensorGroupRowAfter).toBe(sensorGroupRowBefore);

    // 4. The camera group's own row is ALSO the same node -- the flip patches attributes on
    // the existing node rather than replacing it, exactly like the sensor control group.
    expect(cameraGroupRowAfter).toBe(cameraGroupRowBefore);

    // 5. Focus is preserved on the exact same element.
    expect(document.activeElement).toBe(cameraButton);

    // 6. Scroll position is unchanged.
    expect(eventLog.scrollTop).toBe(42);

    // 7. The map placeholder's DOM node identity is preserved.
    expect(screen.getByText("Topology map — Phase 13")).toBe(mapPlaceholderBefore);
  });
});
