export interface SegmentOption {
  value: string;
  label: string;
}

export interface SegmentedControlProps {
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
}

/** Selected segment is highlighted with a white/surface background, per the source guideline. */
export function SegmentedControl({ options, value, onChange }: SegmentedControlProps) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-pill bg-bg-subtle p-1" role="tablist">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={[
              "rounded-pill px-3 py-1.5 text-sm font-medium transition-colors max-w-[120px] truncate",
              active ? "bg-bg-surface text-fg-primary shadow-card" : "text-fg-tertiary hover:text-fg-primary",
            ].join(" ")}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
