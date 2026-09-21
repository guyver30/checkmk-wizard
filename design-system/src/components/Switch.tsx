import { InputHTMLAttributes, forwardRef } from "react";

export type SwitchSize = "sm" | "md" | "lg";

const trackSize: Record<SwitchSize, string> = {
  sm: "h-4 w-7",
  md: "h-5 w-9",
  lg: "h-6 w-11",
};
const thumbSize: Record<SwitchSize, string> = {
  sm: "h-3 w-3 peer-checked:translate-x-3",
  md: "h-4 w-4 peer-checked:translate-x-4",
  lg: "h-5 w-5 peer-checked:translate-x-5",
};

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  size?: SwitchSize;
}

export const Switch = forwardRef<HTMLInputElement, SwitchProps>(
  ({ label, size = "md", className = "", id, disabled, ...props }, ref) => (
    <label className={["inline-flex items-center gap-2", disabled ? "cursor-not-allowed" : "cursor-pointer"].join(" ")}>
      <span className="relative inline-flex shrink-0">
        <input
          ref={ref}
          type="checkbox"
          role="switch"
          id={id}
          disabled={disabled}
          className={[
            "peer appearance-none rounded-pill bg-neutral-300 transition-colors",
            "checked:bg-brand focus-visible:outline-none focus-visible:shadow-focus",
            "disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:checked:bg-neutral-300",
            trackSize[size],
            className,
          ].join(" ")}
          {...props}
        />
        <span
          className={[
            "pointer-events-none absolute left-0.5 top-1/2 -translate-y-1/2 rounded-pill bg-bg-surface shadow-sm transition-transform",
            thumbSize[size],
          ].join(" ")}
        />
      </span>
      {label && <span className="text-sm text-fg-primary">{label}</span>}
    </label>
  )
);
Switch.displayName = "Switch";
