// Edit-mode-only controls for the topology map drawing layer (quick 261005-eln): tool
// picker, stroke and fill swatches, text editing for a selected label, Delete, and the
// Save / Revert pair with an unsaved-changes indicator. All state lives in
// useMapDrawingStore; the pointer handling on the canvas lives in TopologyMap.

import { Button } from "kone-design-system";
import { DRAWING_PALETTE, FONT_SIZES, MAX_TEXT_LENGTH } from "../lib/mapDrawing";
import { useMapDrawingStore, type DrawingTool } from "../store/mapDrawingStore";

const TOOLS: { tool: DrawingTool; label: string }[] = [
  { tool: "none", label: "Hosts" },
  { tool: "select", label: "Select" },
  { tool: "rect", label: "Rectangle" },
  { tool: "ellipse", label: "Ellipse" },
  { tool: "line", label: "Line" },
  { tool: "text", label: "Text" },
];

const TOOL_BUTTON_CLASS =
  "rounded-sm border px-2 py-1 text-xs hover:bg-bg-subtle-hover";

const SWATCH_CLASS = "h-5 w-5 rounded-sm border";

export function MapDrawingToolbar({ onActivity }: { onActivity?: () => void }) {
  const tool = useMapDrawingStore((s) => s.tool);
  const stroke = useMapDrawingStore((s) => s.stroke);
  const fill = useMapDrawingStore((s) => s.fill);
  const dirty = useMapDrawingStore((s) => s.dirty);
  const saving = useMapDrawingStore((s) => s.saving);
  const saveError = useMapDrawingStore((s) => s.saveError);
  const selectedId = useMapDrawingStore((s) => s.selectedId);
  const selected = useMapDrawingStore((s) => s.draft.find((sh) => sh.id === s.selectedId));
  const store = useMapDrawingStore.getState;

  const act = (fn: () => void) => () => {
    fn();
    onActivity?.();
  };

  return (
    <div
      role="toolbar"
      aria-label="Drawing tools"
      className="absolute right-2 top-2 z-10 flex max-w-xs flex-col gap-2 rounded-md border border-neutral-300 bg-bg-surface p-2 shadow-sm"
    >
      <div className="flex flex-wrap gap-1">
        {TOOLS.map(({ tool: t, label }) => (
          <button
            key={t}
            type="button"
            aria-pressed={tool === t}
            title={t === "none" ? "Hosts (no drawing tool): drag and connect hosts as usual" : label}
            onClick={act(() => store().setTool(t))}
            className={`${TOOL_BUTTON_CLASS} ${tool === t ? "border-brand-default bg-bg-subtle font-semibold" : "border-neutral-300"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1" role="group" aria-label="Stroke colour">
        <span className="w-10 text-xs text-fg-tertiary">Stroke</span>
        {DRAWING_PALETTE.map((p) => (
          <button
            key={p.color}
            type="button"
            aria-label={`Stroke ${p.name}`}
            aria-pressed={stroke === p.color}
            onClick={act(() => store().setStroke(p.color))}
            className={`${SWATCH_CLASS} ${stroke === p.color ? "ring-2 ring-offset-1" : ""}`}
            style={{ backgroundColor: p.color }}
          />
        ))}
      </div>

      <div className="flex items-center gap-1" role="group" aria-label="Fill colour">
        <span className="w-10 text-xs text-fg-tertiary">Fill</span>
        <button
          type="button"
          aria-label="No fill"
          aria-pressed={fill === null}
          title="No fill"
          onClick={act(() => store().setFill(null))}
          className={`${SWATCH_CLASS} bg-white text-xs leading-none ${fill === null ? "ring-2 ring-offset-1" : ""}`}
        >
          ∅
        </button>
        {DRAWING_PALETTE.map((p) => (
          <button
            key={p.color}
            type="button"
            aria-label={`Fill ${p.name}`}
            aria-pressed={fill === p.color}
            onClick={act(() => store().setFill(p.color))}
            className={`${SWATCH_CLASS} ${fill === p.color ? "ring-2 ring-offset-1" : ""}`}
            style={{ backgroundColor: p.color }}
          />
        ))}
      </div>

      {selected?.type === "text" && (
        <div className="flex items-center gap-1">
          <input
            type="text"
            aria-label="Label text"
            value={selected.text}
            maxLength={MAX_TEXT_LENGTH}
            onChange={(event) => {
              const text = event.target.value;
              store().updateShape(selected.id, (sh) => (sh.type === "text" ? { ...sh, text } : sh));
              onActivity?.();
            }}
            className="min-w-0 flex-1 rounded-sm border border-neutral-300 px-1 py-0.5 text-xs"
          />
          <select
            aria-label="Label size"
            value={selected.fontSize}
            onChange={(event) => {
              const fontSize = Number(event.target.value);
              store().updateShape(selected.id, (sh) => (sh.type === "text" ? { ...sh, fontSize } : sh));
              onActivity?.();
            }}
            className="rounded-sm border border-neutral-300 px-1 py-0.5 text-xs"
          >
            {FONT_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <Button
          size="sm"
          variant="destructive"
          disabled={selectedId === null}
          onClick={act(() => {
            const id = store().selectedId;
            if (id) store().removeShape(id);
          })}
        >
          Delete
        </Button>
        <Button size="sm" variant="secondary" disabled={!dirty} onClick={act(() => store().revert())}>
          Revert
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={!dirty || saving}
          loading={saving}
          onClick={act(() => void store().save())}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {dirty && <p className="text-xs text-fg-secondary">Unsaved drawing changes</p>}
      {saveError && (
        <p role="alert" className="text-xs text-danger-default">
          {saveError}
        </p>
      )}
    </div>
  );
}
