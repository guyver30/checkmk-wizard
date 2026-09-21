import { ReactNode } from "react";

export interface SelectableCardProps {
  selected: boolean;
  onSelect: () => void;
  title: ReactNode;
  description?: ReactNode;
  subtle?: boolean;
  disabled?: boolean;
}

/**
 * "Area-select" pattern: the whole card is the click target and gets a brand
 * border + focus-style ring when selected. Don't nest another selectable
 * area-select inside one (no multi-level select), per the source guideline.
 */
export function SelectableCard({ selected, onSelect, title, description, subtle = false, disabled = false }: SelectableCardProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={[
        "w-full rounded-md border p-4 text-left transition-colors",
        selected
          ? "border-brand bg-bg-surface shadow-focus"
          : subtle
          ? "border-transparent bg-bg-subtle hover:bg-bg-subtle-hover"
          : "border-neutral-200 bg-bg-surface hover:bg-bg-surface-hover",
        disabled ? "cursor-not-allowed opacity-50" : "",
      ].join(" ")}
    >
      <p className="text-sm font-semibold text-fg-primary">{title}</p>
      {description && <p className="mt-1 text-sm text-fg-tertiary">{description}</p>}
    </button>
  );
}
