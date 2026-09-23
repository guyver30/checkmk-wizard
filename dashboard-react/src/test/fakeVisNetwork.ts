// jsdom does not implement the canvas 2D context (`HTMLCanvasElement.getContext("2d")`
// returns null by default), which vis-network's real `Network` constructor requires in order
// to render -- this FakeNetwork stands in for it in every test, implementing only the surface
// TopologyMap.tsx (and later, 13-06/13-07's manipulation toolbar) actually calls. Registered
// globally via `vi.mock("vis-network/peer", ...)` in vitest.setup.ts, following the same
// "stub what jsdom lacks, comment why" convention Splitter.test.tsx established for
// setPointerCapture/releasePointerCapture.
//
// The real vis-data DataSet is NOT stubbed here -- it is pure JS with no canvas/DOM
// dependency and works fine in jsdom, so TopologyMap.tsx's actual DataSet instances are
// exercised as-is; only the Network class (the thing that would try to touch a canvas) is
// faked.

type EventHandler = (params?: unknown) => void;

// Intentionally loose -- mirrors the real Network constructor's own loose
// (nodes: DataSet, edges: DataSet, options: object) signature closely enough for tests.
export interface FakeNetworkData {
  nodes: { get: (id?: unknown) => unknown; getIds: () => unknown[] };
  edges: { get: (id?: unknown) => unknown; getIds: () => unknown[] };
}

export class FakeNetwork {
  container: HTMLElement;
  data: FakeNetworkData;
  options: Record<string, unknown>;
  setOptionsCalls: Record<string, unknown>[] = [];
  destroyed = false;
  editModeEnabled = false;
  disableEditModeCallCount = 0;

  private handlers: Record<string, EventHandler[]> = {};
  private onceHandlers: Record<string, EventHandler[]> = {};

  constructor(container: HTMLElement, data: FakeNetworkData, options: Record<string, unknown>) {
    this.container = container;
    this.data = data;
    this.options = options;
    instances.push(this);
  }

  on(event: string, handler: EventHandler): void {
    (this.handlers[event] ??= []).push(handler);
  }

  once(event: string, handler: EventHandler): void {
    (this.onceHandlers[event] ??= []).push(handler);
  }

  off(event: string, handler?: EventHandler): void {
    if (!handler) {
      delete this.handlers[event];
      return;
    }
    this.handlers[event] = (this.handlers[event] ?? []).filter((h) => h !== handler);
  }

  setOptions(opts: Record<string, unknown>): void {
    this.options = { ...this.options, ...opts };
    this.setOptionsCalls.push(opts);
  }

  destroy(): void {
    this.destroyed = true;
  }

  getPositions(ids: string[]): Record<string, { x: number; y: number }> {
    const result: Record<string, { x: number; y: number }> = {};
    for (const id of ids) {
      const item = this.data.nodes.get(id) as { x?: number; y?: number } | null;
      if (item) {
        result[id] = { x: item.x ?? 0, y: item.y ?? 0 };
      }
    }
    return result;
  }

  disableEditMode(): void {
    this.editModeEnabled = false;
    this.disableEditModeCallCount += 1;
  }

  enableEditMode(): void {
    this.editModeEnabled = true;
  }

  addEdgeMode(): void {
    // No-op in tests -- the real toolbar arrives in 13-06/13-07.
  }

  // 13-06: the manipulation option object (addEdge/editEdge/deleteEdge/addNode functions) is
  // set via setOptions(), same as every other option -- this.options already accumulates every
  // setOptions() call (see setOptions() above), so exposing it here just gives tests direct
  // access to invoke those callbacks without reaching into setOptionsCalls themselves.
  lastManipulation(): Record<string, unknown> | undefined {
    return this.options.manipulation as Record<string, unknown> | undefined;
  }

  // Test-only helper: fires every registered `on`/`once` handler for `event`, then clears the
  // `once` handlers for it, mirroring vis-network's own once() semantics.
  emit(event: string, params?: unknown): void {
    for (const handler of this.handlers[event] ?? []) {
      handler(params);
    }
    const once = this.onceHandlers[event];
    if (once) {
      delete this.onceHandlers[event];
      for (const handler of once) {
        handler(params);
      }
    }
  }
}

export const instances: FakeNetwork[] = [];

export function resetFakeNetworks(): void {
  instances.length = 0;
}
