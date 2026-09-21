import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePaneLayout } from "./usePaneLayout";

const STORAGE_KEY = "dashboard-react.paneLayout.v1";

describe("usePaneLayout", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("returns the default sizes, both uncollapsed, on first mount with empty storage", () => {
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes).toEqual({ tree: 320, events: 260 });
    expect(result.current.collapsed).toEqual({ tree: false, events: false });
  });

  it("returns the persisted sizes on mount with a valid persisted record", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ treeWidth: 400, eventsHeight: 300, treeCollapsed: false, eventsCollapsed: false }),
    );
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes).toEqual({ tree: 400, events: 300 });
  });

  it("returns defaults without throwing on mount with a corrupt persisted value", () => {
    localStorage.setItem(STORAGE_KEY, "not json{");
    let hook: ReturnType<typeof renderHook<ReturnType<typeof usePaneLayout>, unknown>> | undefined;
    expect(() => {
      hook = renderHook(() => usePaneLayout());
    }).not.toThrow();
    expect(hook?.result.current.sizes).toEqual({ tree: 320, events: 260 });
  });

  it("clamps a persisted size outside [min, max] into range rather than honouring it", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ treeWidth: 99999 }));
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes.tree).toBe(640);
  });

  it("setSize updates the returned size immediately", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.setSize("tree", 480);
    });
    expect(result.current.sizes.tree).toBe(480);
  });

  it("commit leaves the in-memory size at its new value even when localStorage.setItem throws", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.setSize("tree", 480);
    });
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => {
      act(() => {
        result.current.commit();
      });
    }).not.toThrow();
    expect(result.current.sizes.tree).toBe(480);
    spy.mockRestore();
  });

  it("toggleCollapse flips the flag, persists it, and restoring returns to the previous size", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.setSize("events", 350);
    });
    act(() => {
      result.current.toggleCollapse("events");
    });
    expect(result.current.collapsed.events).toBe(true);
    expect(result.current.sizes.events).toBe(350);

    act(() => {
      result.current.toggleCollapse("events");
    });
    expect(result.current.collapsed.events).toBe(false);
    expect(result.current.sizes.events).toBe(350);
  });
});
