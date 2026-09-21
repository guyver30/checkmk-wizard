export interface StepData {
  id: string;
  label: string;
}

export interface StepsProps {
  steps: StepData[];
  currentIndex: number;
}

/** Horizontal wizard-style step indicator: done / current / upcoming. */
export function Steps({ steps, currentIndex }: StepsProps) {
  return (
    <ol className="flex items-center">
      {steps.map((step, index) => {
        const done = index < currentIndex;
        const current = index === currentIndex;
        return (
          <li key={step.id} className="flex flex-1 items-center last:flex-none">
            <span className="flex items-center gap-2">
              <span
                className={[
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-pill text-xs font-semibold",
                  done
                    ? "bg-brand text-fg-oncolor"
                    : current
                    ? "bg-brand text-fg-oncolor"
                    : "border border-neutral-300 text-fg-tertiary",
                ].join(" ")}
              >
                {done ? "✓" : index + 1}
              </span>
              <span className={["text-sm", current ? "font-semibold text-fg-primary" : "text-fg-tertiary"].join(" ")}>
                {step.label}
              </span>
            </span>
            {index < steps.length - 1 && <span className="mx-3 h-px flex-1 bg-neutral-200" />}
          </li>
        );
      })}
    </ol>
  );
}
