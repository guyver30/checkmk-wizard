import { ReactNode, useState } from "react";

export interface AccordionItemData {
  id: string;
  title: ReactNode;
  content: ReactNode;
}

export interface AccordionProps {
  items: AccordionItemData[];
  defaultOpenId?: string;
}

/**
 * Vertical stack of collapsible sections. Radius is only applied to the
 * outer-most corners of the group, per the source guideline's note. The
 * source guideline also says: do not put forms or buttons inside an
 * accordion item -- keep content read-only (e.g. FAQ copy).
 */
export function Accordion({ items, defaultOpenId }: AccordionProps) {
  const [openId, setOpenId] = useState<string | undefined>(defaultOpenId);

  return (
    <div className="overflow-hidden rounded-md border border-neutral-150">
      {items.map((item, index) => {
        const isOpen = openId === item.id;
        return (
          <div key={item.id} className={index > 0 ? "border-t border-neutral-150" : undefined}>
            <button
              type="button"
              onClick={() => setOpenId(isOpen ? undefined : item.id)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between gap-3 bg-bg-subtle px-4 py-3 text-left hover:bg-bg-subtle-hover"
            >
              <span className="text-sm font-semibold text-fg-primary">{item.title}</span>
              <span
                className={[
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-pill border border-neutral-300 bg-bg-surface text-fg-secondary transition-transform",
                  isOpen ? "rotate-180" : "",
                ].join(" ")}
                aria-hidden
              >
                &#9660;
              </span>
            </button>
            {isOpen && <div className="bg-bg-subtle px-4 pb-4 text-sm text-fg-secondary">{item.content}</div>}
          </div>
        );
      })}
    </div>
  );
}
