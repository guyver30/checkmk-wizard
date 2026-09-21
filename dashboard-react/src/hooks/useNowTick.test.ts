import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLOCK_TICK_MS, useNowTick } from "./useNowTick";

describe("useNowTick", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("exports CLOCK_TICK_MS as 12000", () => {
    expect(CLOCK_TICK_MS).toBe(12000);
  });

  it("advances by roughly intervalMs on each interval fire", () => {
    const { result } = renderHook(() => useNowTick(1000));
    const initial = result.current;

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(result.current - initial).toBe(1000);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current - initial).toBe(4000);
  });

  it("defaults to CLOCK_TICK_MS when no interval is given", () => {
    const { result } = renderHook(() => useNowTick());
    const initial = result.current;

    act(() => {
      vi.advanceTimersByTime(CLOCK_TICK_MS);
    });

    expect(result.current - initial).toBe(CLOCK_TICK_MS);
  });

  it("clears its interval on unmount, leaving no timer leak", () => {
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");
    const { result, unmount } = renderHook(() => useNowTick(1000));
    const beforeUnmount = result.current;

    unmount();

    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);

    // Advancing timers after unmount must not schedule any further update -- there is
    // nothing left to observe it through, but a leaked interval would still fire its
    // (now orphaned) setState callback, which React would warn about.
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current).toBe(beforeUnmount);
    clearIntervalSpy.mockRestore();
  });
});
