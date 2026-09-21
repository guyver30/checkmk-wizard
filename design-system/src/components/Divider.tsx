export interface DividerProps {
  orientation?: "horizontal" | "vertical";
}

/** For separating content within a container -- not for decorative use. */
export function Divider({ orientation = "horizontal" }: DividerProps) {
  return orientation === "horizontal" ? (
    <hr className="w-full border-t border-neutral-150" />
  ) : (
    <span className="h-full w-px self-stretch bg-neutral-150" role="separator" aria-orientation="vertical" />
  );
}
