import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KIOSK_ROTATION_MS, useKioskRotation } from "./useKioskRotation";

describe("useKioskRotation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("exports KIOSK_ROTATION_MS as 20000", () => {
    expect(KIOSK_ROTATION_MS).toBe(20000);
  });

  it("starts at incidents, cycle 0", () => {
    const { result } = renderHook(() => useKioskRotation());
    expect(result.current).toEqual({ view: "incidents", cycle: 0 });
  });

  it("flips to topology after 20000ms, then back to incidents after another 20000ms", () => {
    const { result } = renderHook(() => useKioskRotation());

    act(() => {
      vi.advanceTimersByTime(KIOSK_ROTATION_MS);
    });
    expect(result.current).toEqual({ view: "topology", cycle: 1 });

    act(() => {
      vi.advanceTimersByTime(KIOSK_ROTATION_MS);
    });
    expect(result.current).toEqual({ view: "incidents", cycle: 2 });
  });

  it("clears its interval on unmount", () => {
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");
    const { unmount } = renderHook(() => useKioskRotation());

    unmount();

    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    clearIntervalSpy.mockRestore();
  });
});
