export interface FilterChipProps {
  label: string;
  onRemove: () => void;
}

/** The whole chip is interactive; clicking it removes the applied filter. */
export function FilterChip({ label, onRemove }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onRemove}
      className="inline-flex items-center gap-1.5 rounded-sm border border-neutral-300 bg-bg-surface px-2.5 py-1 text-sm font-medium text-fg-primary hover:bg-bg-surface-hover"
    >
      {label}
      <span aria-hidden>&#10005;</span>
    </button>
  );
}

export interface SelectorChipProps {
  label: string;
  selected: boolean;
  onToggle: () => void;
}

/** Radio-like alternative for exclusive choices, rendered as a pill chip. */
export function SelectorChip({ label, selected, onToggle }: SelectorChipProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onToggle}
      className={[
        "inline-flex items-center gap-2 rounded-pill border px-3 py-1.5 text-sm font-medium",
        selected ? "border-brand text-fg-primary" : "border-neutral-300 text-fg-primary hover:bg-bg-surface-hover",
      ].join(" ")}
    >
      <span
        className={[
          "flex h-4 w-4 items-center justify-center rounded-pill border-2",
          selected ? "border-brand" : "border-neutral-400",
        ].join(" ")}
      >
        {selected && <span className="h-2 w-2 rounded-pill bg-brand" />}
      </span>
      {label}
    </button>
  );
}
