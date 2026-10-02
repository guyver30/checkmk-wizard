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
    expect(result.current.sizes).toEqual({ tree: 320, events: 260, details: 420, incidents: 280 });
    expect(result.current.collapsed).toEqual({ tree: false, events: false, details: false, incidents: false });
  });

  it("returns the persisted sizes on mount with a valid persisted record", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ treeWidth: 400, eventsHeight: 300, treeCollapsed: false, eventsCollapsed: false }),
    );
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes).toEqual({ tree: 400, events: 300, details: 420, incidents: 280 });
  });

  it("returns defaults without throwing on mount with a corrupt persisted value", () => {
    localStorage.setItem(STORAGE_KEY, "not json{");
    let hook: ReturnType<typeof renderHook<ReturnType<typeof usePaneLayout>, unknown>> | undefined;
    expect(() => {
      hook = renderHook(() => usePaneLayout());
    }).not.toThrow();
    expect(hook?.result.current.sizes).toEqual({ tree: 320, events: 260, details: 420, incidents: 280 });
  });

  it("clamps a persisted detailsWidth outside [min, max] and defaults detailsCollapsed to false", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ detailsWidth: 99999 }));
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes.details).toBe(800);
    expect(result.current.collapsed.details).toBe(false);
  });

  it("an old persisted record without the details fields still restores treeWidth/eventsHeight", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ treeWidth: 500, eventsHeight: 280, treeCollapsed: true, eventsCollapsed: false }),
    );
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes).toEqual({ tree: 500, events: 280, details: 420, incidents: 280 });
    expect(result.current.collapsed).toEqual({ tree: true, events: false, details: false, incidents: false });
  });

  it("clamps a persisted incidentsHeight, falls back a non-boolean incidentsCollapsed, keeps older fields", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ treeWidth: 500, incidentsHeight: 99999, incidentsCollapsed: "x" }),
    );
    const { result } = renderHook(() => usePaneLayout());
    expect(result.current.sizes.incidents).toBe(600);
    expect(result.current.collapsed.incidents).toBe(false);
    expect(result.current.sizes.tree).toBe(500);
  });

  it("toggleCollapse('incidents') flips the flag and persists incidentsCollapsed in the same record", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => result.current.toggleCollapse("incidents"));
    expect(result.current.collapsed.incidents).toBe(true);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}").incidentsCollapsed).toBe(true);
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

  it("toggleCollapse persists all eight fields, including the details pane's current state", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.setSize("details", 500);
    });
    act(() => {
      result.current.toggleCollapse("tree");
    });
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
    expect(persisted).toEqual({
      treeWidth: 320,
      eventsHeight: 260,
      treeCollapsed: true,
      eventsCollapsed: false,
      detailsWidth: 500,
      detailsCollapsed: false,
      incidentsHeight: 280,
      incidentsCollapsed: false,
    });
  });

  it("commit persists all eight fields", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.setSize("details", 500);
    });
    act(() => {
      result.current.commit();
    });
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
    expect(persisted).toEqual({
      treeWidth: 320,
      eventsHeight: 260,
      treeCollapsed: false,
      eventsCollapsed: false,
      detailsWidth: 500,
      detailsCollapsed: false,
      incidentsHeight: 280,
      incidentsCollapsed: false,
    });
  });

  it("expand sets collapsed false and writes storage, and is a no-op when already expanded", () => {
    const { result } = renderHook(() => usePaneLayout());
    act(() => {
      result.current.toggleCollapse("details");
    });
    expect(result.current.collapsed.details).toBe(true);

    act(() => {
      result.current.expand("details");
    });
    expect(result.current.collapsed.details).toBe(false);
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) as string);
    expect(persisted.detailsCollapsed).toBe(false);

    // No-op when already expanded: state reference is unchanged, no re-render triggered by it.
    const before = result.current;
    act(() => {
      result.current.expand("details");
    });
    expect(result.current.collapsed).toBe(before.collapsed);
  });
});
