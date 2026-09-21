import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useGroupingPrefs } from "./useGroupingPrefs";

const STORAGE_KEY = "dashboard-react.grouping.v1";

describe("useGroupingPrefs", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("returns { mode: 'type', orderBySeverity: false } on first run with empty storage", () => {
    const { result } = renderHook(() => useGroupingPrefs());
    expect(result.current.mode).toBe("type");
    expect(result.current.orderBySeverity).toBe(false);
  });

  it("restores a valid stored record on mount", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode: "folder", orderBySeverity: true }));
    const { result } = renderHook(() => useGroupingPrefs());
    expect(result.current.mode).toBe("folder");
    expect(result.current.orderBySeverity).toBe(true);
  });

  it("falls back to defaults without throwing when the stored record is corrupt", () => {
    localStorage.setItem(STORAGE_KEY, "not json{");
    let hook: ReturnType<typeof renderHook<ReturnType<typeof useGroupingPrefs>, unknown>> | undefined;
    expect(() => {
      hook = renderHook(() => useGroupingPrefs());
    }).not.toThrow();
    expect(hook?.result.current.mode).toBe("type");
    expect(hook?.result.current.orderBySeverity).toBe(false);
  });

  it("falls back mode to 'type' when the stored mode is not in the known option list", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode: "bogus", orderBySeverity: false }));
    const { result } = renderHook(() => useGroupingPrefs());
    expect(result.current.mode).toBe("type");
  });

  it("setMode updates the returned mode immediately even when localStorage.setItem throws", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useGroupingPrefs());
    act(() => {
      result.current.setMode("folder");
    });
    expect(result.current.mode).toBe("folder");
    spy.mockRestore();
  });

  it("setOrderBySeverity updates the returned value immediately even when localStorage.setItem throws", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useGroupingPrefs());
    act(() => {
      result.current.setOrderBySeverity(true);
    });
    expect(result.current.orderBySeverity).toBe(true);
    spy.mockRestore();
  });

  it("persists mode and orderBySeverity under the versioned storage key", () => {
    const { result } = renderHook(() => useGroupingPrefs());
    act(() => {
      result.current.setMode("folder");
    });
    act(() => {
      result.current.setOrderBySeverity(true);
    });
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(persisted).toEqual({ mode: "folder", orderBySeverity: true });
  });
});
