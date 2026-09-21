import { ReactNode } from "react";

export interface ButtonGroupProps {
  children: ReactNode;
  /** Stacks buttons full-width -- required in mobile layouts per the source guideline. */
  fill?: boolean;
}

/**
 * Arranges related buttons together. Only one primary CTA should be used per
 * group (placed last/right), per the source guideline.
 */
export function ButtonGroup({ children, fill = false }: ButtonGroupProps) {
  return <div className={["flex items-center gap-3", fill ? "flex-col [&>*]:w-full" : ""].join(" ")}>{children}</div>;
}
