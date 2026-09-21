import { InputHTMLAttributes, forwardRef, useEffect, useRef } from "react";

export type CheckboxSize = "sm" | "md";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  size?: CheckboxSize;
  indeterminate?: boolean;
}

const boxSize: Record<CheckboxSize, string> = { sm: "h-4 w-4", md: "h-5 w-5" };

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, size = "md", indeterminate = false, className = "", id, disabled, ...props }, ref) => {
    const innerRef = useRef<HTMLInputElement | null>(null);

    useEffect(() => {
      if (innerRef.current) innerRef.current.indeterminate = indeterminate;
    }, [indeterminate]);

    return (
      <label className={["inline-flex items-center gap-2", disabled ? "cursor-not-allowed" : "cursor-pointer"].join(" ")}>
        <span className="relative inline-flex">
          <input
            ref={(node) => {
              innerRef.current = node;
              if (typeof ref === "function") ref(node);
              else if (ref) (ref as React.MutableRefObject<HTMLInputElement | null>).current = node;
            }}
            type="checkbox"
            id={id}
            disabled={disabled}
            className={[
              "peer appearance-none rounded-xs border border-neutral-400 bg-bg-surface transition-colors",
              "checked:border-brand checked:bg-brand indeterminate:border-brand indeterminate:bg-brand",
              "focus-visible:outline-none focus-visible:shadow-focus",
              "disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-bg-surface-disabled disabled:checked:bg-neutral-300 disabled:checked:border-neutral-300",
              boxSize[size],
              className,
            ].join(" ")}
            {...props}
          />
          <svg
            aria-hidden
            viewBox="0 0 16 16"
            className="pointer-events-none absolute inset-0 hidden h-full w-full p-0.5 text-fg-oncolor peer-checked:block peer-indeterminate:hidden"
          >
            <path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <svg
            aria-hidden
            viewBox="0 0 16 16"
            className="pointer-events-none absolute inset-0 hidden h-full w-full p-0.5 text-fg-oncolor peer-indeterminate:block"
          >
            <path d="M3.5 8h9" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </span>
        {label && <span className="text-sm text-fg-primary">{label}</span>}
      </label>
    );
  }
);
Checkbox.displayName = "Checkbox";
