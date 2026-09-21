export interface PaginationProps {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
}

function pageList(page: number, pageCount: number): (number | "ellipsis")[] {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, i) => i + 1);
  const pages = new Set([1, pageCount, page - 1, page, page + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= pageCount).sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - (sorted[i - 1] as number) > 1) result.push("ellipsis");
    result.push(p);
  });
  return result;
}

const navButton =
  "flex h-8 w-8 items-center justify-center rounded-sm text-fg-secondary hover:bg-bg-surface-hover disabled:cursor-not-allowed disabled:text-fg-disabled disabled:hover:bg-transparent";

export function Pagination({ page, pageCount, onPageChange }: PaginationProps) {
  return (
    <nav className="flex items-center gap-1" aria-label="Pagination">
      <button className={navButton} disabled={page <= 1} onClick={() => onPageChange(1)} aria-label="First page">
        &#171;
      </button>
      <button className={navButton} disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">
        &#8249;
      </button>
      {pageList(page, pageCount).map((p, i) =>
        p === "ellipsis" ? (
          <span key={`e${i}`} className="flex h-8 w-8 items-center justify-center text-fg-tertiary">
            &hellip;
          </span>
        ) : (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            aria-current={p === page ? "page" : undefined}
            className={[
              "flex h-8 w-8 items-center justify-center rounded-sm text-sm",
              p === page ? "bg-brand-light font-semibold text-fg-brand" : "text-fg-secondary hover:bg-bg-surface-hover",
            ].join(" ")}
          >
            {p}
          </button>
        )
      )}
      <button className={navButton} disabled={page >= pageCount} onClick={() => onPageChange(page + 1)} aria-label="Next page">
        &#8250;
      </button>
      <button className={navButton} disabled={page >= pageCount} onClick={() => onPageChange(pageCount)} aria-label="Last page">
        &#187;
      </button>
    </nav>
  );
}
