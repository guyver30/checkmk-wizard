// Edit-session state for the topology map drawing layer (quick 261005-eln). Like
// IndexRoute's editMode this is deliberately NOT persisted anywhere in the browser: the
// draft lives in memory only, survives leaving edit mode (so an idle timeout cannot lose
// work), and is gone on reload (TopologyMap warns via beforeunload while it is dirty).
// Last write wins on save: no ETag, no merge.

import { create } from "zustand";
import { DEFAULT_STROKE, emptyDrawing, type Drawing, type Shape } from "../lib/mapDrawing";
import { loadDrawing, saveDrawing } from "../lib/mapDrawingClient";

export type DrawingTool = "none" | "select" | "rect" | "ellipse" | "line" | "text";

interface MapDrawingState {
  saved: Drawing;
  draft: Shape[];
  dirty: boolean;
  selectedId: string | null;
  tool: DrawingTool;
  stroke: string;
  fill: string | null;
  loading: boolean;
  loadError: string | null;
  saving: boolean;
  saveError: string | null;
  load: () => Promise<void>;
  save: () => Promise<void>;
  revert: () => void;
  addShape: (shape: Shape) => void;
  updateShape: (id: string, next: Shape | ((s: Shape) => Shape)) => void;
  removeShape: (id: string) => void;
  select: (id: string | null) => void;
  setTool: (tool: DrawingTool) => void;
  setStroke: (color: string) => void;
  setFill: (color: string | null) => void;
  clearErrors: () => void;
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : "Unknown error";
}

const initial = () => ({
  saved: emptyDrawing(),
  draft: [] as Shape[],
  dirty: false,
  selectedId: null as string | null,
  tool: "none" as DrawingTool,
  stroke: DEFAULT_STROKE,
  fill: null as string | null,
  loading: false,
  loadError: null as string | null,
  saving: false,
  saveError: null as string | null,
});

export const useMapDrawingStore = create<MapDrawingState>((set, get) => ({
  ...initial(),

  async load() {
    if (get().loading) return;
    set({ loading: true, loadError: null });
    try {
      const d = await loadDrawing();
      // A dirty draft is the operator's unsaved work: only refresh the saved copy.
      set((s) => (s.dirty ? { saved: d } : { saved: d, draft: d.shapes }));
    } catch (err) {
      set({ loadError: message(err) });
    } finally {
      set({ loading: false });
    }
  },

  async save() {
    if (get().saving) return;
    const snapshot = get().draft;
    set({ saving: true, saveError: null });
    try {
      const saved = await saveDrawing(snapshot);
      // Edits made while the PUT was in flight keep the draft dirty.
      set((s) => ({ saved, dirty: s.draft !== snapshot }));
    } catch (err) {
      set({ saveError: message(err) });
    } finally {
      set({ saving: false });
    }
  },

  revert() {
    set((s) => ({ draft: s.saved.shapes, dirty: false, selectedId: null, saveError: null }));
  },

  addShape(shape) {
    set((s) => ({ draft: [...s.draft, shape], dirty: true }));
  },

  updateShape(id, next) {
    set((s) => ({
      draft: s.draft.map((sh) => (sh.id === id ? (typeof next === "function" ? next(sh) : next) : sh)),
      dirty: true,
    }));
  },

  removeShape(id) {
    set((s) => ({
      draft: s.draft.filter((sh) => sh.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId,
      dirty: true,
    }));
  },

  select(id) {
    set({ selectedId: id });
  },

  setTool(tool) {
    set({ tool });
  },

  setStroke(color) {
    const { selectedId } = get();
    set({ stroke: color });
    if (selectedId) get().updateShape(selectedId, (sh) => ({ ...sh, stroke: color }));
  },

  setFill(color) {
    const { selectedId } = get();
    set({ fill: color });
    if (selectedId) {
      get().updateShape(selectedId, (sh) =>
        sh.type === "rect" || sh.type === "ellipse" ? { ...sh, fill: color } : sh,
      );
    }
  },

  clearErrors() {
    set({ loadError: null, saveError: null });
  },
}));

export function __resetMapDrawingStoreForTests(): void {
  useMapDrawingStore.setState(initial());
}
