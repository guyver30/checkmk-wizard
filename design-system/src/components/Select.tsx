import { ReactNode, SelectHTMLAttributes, forwardRef } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  label?: ReactNode;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
}

/** Single-select dropdown. For >7 options, prefer a searchable combobox variant. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, options, placeholder = "Select", className = "", id, ...props }, ref) => (
    <label className="flex flex-col gap-1.5" htmlFor={id}>
      {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
      <span className="relative flex items-center">
        <select
          ref={ref}
          id={id}
          className={[
            "w-full appearance-none rounded-sm border bg-bg-surface py-2 pl-3 pr-8 text-sm text-fg-primary transition-colors",
            "focus:outline-none focus:shadow-focus",
            error ? "border-alert focus:border-alert" : "border-neutral-300 hover:border-neutral-400 focus:border-brand",
            "disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-bg-surface-disabled disabled:text-fg-disabled",
            className,
          ].join(" ")}
          aria-invalid={Boolean(error)}
          defaultValue=""
          {...props}
        >
          <option value="" disabled>
            {placeholder}
          </option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-3 text-fg-tertiary" aria-hidden>
          &#9662;
        </span>
      </span>
      {error && <span className="text-xs text-fg-danger">{error}</span>}
    </label>
  )
);
Select.displayName = "Select";
