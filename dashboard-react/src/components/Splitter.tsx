import { useRef } from "react";

export type SplitterOrientation = "vertical" | "horizontal";

export interface SplitterProps {
  orientation: SplitterOrientation;
  value: number;
  min: number;
  max: number;
  step?: number;
  label: string;
  onResize: (next: number) => void;
  onResizeCommit?: (next: number) => void;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

interface DragState {
  startPos: number;
  startValue: number;
  lastValue: number;
}

/**
 * A controlled, custom resize handle meeting D-26's full keyboard + ARIA separator
 * contract: `role="separator"` with `aria-orientation`/`aria-valuenow`/`aria-valuemin`/
 * `aria-valuemax`, arrow-key resize (ArrowLeft/ArrowRight for vertical, ArrowUp/ArrowDown
 * for horizontal, Home/End to jump to the bounds), and pointer-drag resize. Moving the
 * pointer right (vertical) or down (horizontal) always increases `value`; callers that
 * need the opposite sense for a given pane wire that up in how they compute the size they
 * pass in, not by inverting this component.
 *
 * `onResize` fires on every pointer move / keypress (in-memory state is the source of
 * truth for the session, per D-26); `onResizeCommit` fires exactly once, when the drag
 * ends or a keypress is handled, so a consumer can persist without writing on every pixel.
 */
export function Splitter({
  orientation,
  value,
  min,
  max,
  step = 16,
  label,
  onResize,
  onResizeCommit,
}: SplitterProps) {
  const dragRef = useRef<DragState | null>(null);

  function handlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    // jsdom does not implement setPointerCapture/releasePointerCapture; the test file
    // stubs both on the element so this call is a no-op there rather than a throw.
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      startPos: orientation === "vertical" ? e.clientX : e.clientY,
      startValue: value,
      lastValue: value,
    };
  }

  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    const pos = orientation === "vertical" ? e.clientX : e.clientY;
    const next = clamp(drag.startValue + (pos - drag.startPos), min, max);
    drag.lastValue = next;
    onResize(next);
  }

  function handlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
    onResizeCommit?.(drag.lastValue);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    let next: number | null = null;
    if (orientation === "vertical") {
      if (e.key === "ArrowRight") {
        next = value + step;
      } else if (e.key === "ArrowLeft") {
        next = value - step;
      }
    } else {
      if (e.key === "ArrowDown") {
        next = value + step;
      } else if (e.key === "ArrowUp") {
        next = value - step;
      }
    }
    if (e.key === "Home") {
      next = min;
    } else if (e.key === "End") {
      next = max;
    }

    if (next === null) {
      return;
    }
    e.preventDefault();
    const clamped = clamp(next, min, max);
    onResize(clamped);
    onResizeCommit?.(clamped);
  }

  const thinAxisClass = orientation === "vertical" ? "cursor-col-resize" : "cursor-row-resize";

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation={orientation}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-label={label}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      className={[
        "select-none bg-neutral-150 hover:bg-neutral-300 focus:shadow-focus focus:outline-none",
        thinAxisClass,
        orientation === "vertical" ? "h-full w-1" : "h-1 w-full",
      ].join(" ")}
    />
  );
}
