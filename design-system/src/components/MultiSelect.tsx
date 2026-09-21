import { useState } from "react";
import { Checkbox } from "./Checkbox";

export interface MultiSelectOption {
  value: string;
  label: string;
}

export interface MultiSelectProps {
  label?: string;
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}

/** Multi-select dropdown: trigger summarizes selection, panel lists checkboxes. */
export function MultiSelect({ label, options, value, onChange, placeholder = "Select" }: MultiSelectProps) {
  const [open, setOpen] = useState(false);

  const toggle = (v: string) => {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  };

  const summary =
    value.length === 0 ? placeholder : value.length === 1 ? options.find((o) => o.value === value[0])?.label : `${value.length} selected`;

  return (
    <div className="relative flex flex-col gap-1.5">
      {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={[
          "flex h-9 items-center justify-between rounded-sm border bg-bg-surface px-3 text-sm transition-colors",
          open ? "border-brand shadow-focus" : "border-neutral-300 hover:border-neutral-400",
          value.length === 0 ? "text-fg-placeholder" : "text-fg-primary",
        ].join(" ")}
      >
        {summary}
        <span aria-hidden className="text-fg-tertiary">
          &#9662;
        </span>
      </button>
      {open && (
        <div className="absolute top-full z-10 mt-1 w-full min-w-[200px] rounded-md border border-neutral-150 bg-bg-surface py-1.5 shadow-menu">
          {options.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm text-fg-primary hover:bg-bg-surface-hover"
            >
              <Checkbox size="sm" checked={value.includes(option.value)} onChange={() => toggle(option.value)} />
              {option.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
