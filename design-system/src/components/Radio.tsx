import { InputHTMLAttributes, ReactNode, forwardRef } from "react";

export type RadioSize = "sm" | "md" | "lg";

const boxSize: Record<RadioSize, string> = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-6 w-6" };
const dotSize: Record<RadioSize, string> = { sm: "h-1.5 w-1.5", md: "h-2 w-2", lg: "h-2.5 w-2.5" };

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: ReactNode;
  hint?: ReactNode;
  size?: RadioSize;
}

export const Radio = forwardRef<HTMLInputElement, RadioProps>(
  ({ label, hint, size = "md", className = "", id, disabled, ...props }, ref) => (
    <label className={["inline-flex items-start gap-2", disabled ? "cursor-not-allowed" : "cursor-pointer"].join(" ")}>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input
          ref={ref}
          type="radio"
          id={id}
          disabled={disabled}
          className={[
            "peer appearance-none rounded-pill border-2 border-neutral-400 bg-bg-surface transition-colors",
            "checked:border-brand focus-visible:outline-none focus-visible:shadow-focus",
            "disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-bg-surface-disabled",
            boxSize[size],
            className,
          ].join(" ")}
          {...props}
        />
        <span
          className={[
            "pointer-events-none absolute inset-0 m-auto hidden rounded-pill bg-brand peer-checked:block peer-disabled:bg-neutral-300",
            dotSize[size],
          ].join(" ")}
        />
      </span>
      {(label || hint) && (
        <span className="flex flex-col">
          {label && <span className="text-sm text-fg-primary">{label}</span>}
          {hint && <span className="text-xs text-fg-tertiary">{hint}</span>}
        </span>
      )}
    </label>
  )
);
Radio.displayName = "Radio";
