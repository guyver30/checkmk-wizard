import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EDIT_IDLE_TIMEOUT_MS, useEditIdleTimeout } from "./useEditIdleTimeout";

describe("useEditIdleTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("exports EDIT_IDLE_TIMEOUT_MS as 5 minutes", () => {
    expect(EDIT_IDLE_TIMEOUT_MS).toBe(5 * 60 * 1000);
  });

  it("fires onTimeout once after 5 minutes when active", () => {
    const onTimeout = vi.fn();
    renderHook(() => useEditIdleTimeout(true, onTimeout));

    act(() => {
      vi.advanceTimersByTime(EDIT_IDLE_TIMEOUT_MS);
    });

    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it("touch() restarts the window: touching at 4 min means no fire at 5 min, but a fire at 9 min", () => {
    const onTimeout = vi.fn();
    const { result } = renderHook(() => useEditIdleTimeout(true, onTimeout));

    act(() => {
      vi.advanceTimersByTime(4 * 60 * 1000);
    });
    act(() => {
      result.current.touch();
    });
    act(() => {
      vi.advanceTimersByTime(1 * 60 * 1000);
    });
    expect(onTimeout).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(4 * 60 * 1000);
    });
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it("never fires when active is false, and clears any timer on unmount", () => {
    const onTimeout = vi.fn();
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    const { unmount } = renderHook(() => useEditIdleTimeout(false, onTimeout));

    act(() => {
      vi.advanceTimersByTime(EDIT_IDLE_TIMEOUT_MS * 2);
    });
    expect(onTimeout).not.toHaveBeenCalled();

    unmount();
    clearTimeoutSpy.mockRestore();
  });
});
