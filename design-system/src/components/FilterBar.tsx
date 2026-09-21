import { ReactNode } from "react";
import { FilterChip } from "./Chip";

export interface FilterTrigger {
  id: string;
  label: string;
  onClick?: () => void;
}

export interface AppliedFilter {
  id: string;
  label: string;
}

export interface FilterBarProps {
  triggers: FilterTrigger[];
  applied?: AppliedFilter[];
  onRemove?: (id: string) => void;
  onResetAll?: () => void;
  trailing?: ReactNode;
}

/**
 * The source guideline notes FDS has no pre-built filter component, only a
 * pattern: trigger pills that open a filter panel/menu (compose with Menu.tsx
 * or a custom popover), plus a row of applied filters with a reset action.
 */
export function FilterBar({ triggers, applied = [], onRemove, onResetAll, trailing }: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {triggers.map((t) => (
          <button
            key={t.id}
            onClick={t.onClick}
            className="inline-flex items-center gap-1 rounded-pill bg-bg-subtle px-3 py-1.5 text-sm font-medium text-fg-primary hover:bg-bg-subtle-hover"
          >
            {t.label}
            <span aria-hidden className="text-fg-tertiary">
              &#8250;
            </span>
          </button>
        ))}
        {applied.map((f) => (
          <FilterChip key={f.id} label={f.label} onRemove={() => onRemove?.(f.id)} />
        ))}
        {applied.length > 0 && (
          <button onClick={onResetAll} className="text-sm font-medium text-fg-link hover:text-brand-active">
            Reset filter
          </button>
        )}
      </div>
      {trailing}
    </div>
  );
}
