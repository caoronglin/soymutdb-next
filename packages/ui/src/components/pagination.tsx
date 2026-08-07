import * as React from "react";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { cn, formatNumber } from "../lib/utils";
import { Button } from "./button";

export interface PaginationProps {
  /** Current page (1-based) */
  page: number;
  /** Total number of pages */
  totalPages: number;
  /** Total item count */
  total: number;
  /** Items per page */
  pageSize: number;
  /** Callback when the page changes */
  onPageChange: (page: number) => void;
  /** Whether controls are disabled (e.g. during loading) */
  disabled?: boolean;
  /** Accessible label for the navigation region */
  label?: string;
  className?: string;
}

/**
 * Accessible pagination with first/prev/next/last controls and a
 * compact page-number window. Keyboard navigable, reduced-motion friendly.
 */
export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  disabled = false,
  label = "Pagination",
  className,
}: PaginationProps) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  const pages = React.useMemo(() => {
    const window = 1;
    const result: (number | "…")[] = [];
    const start = Math.max(1, page - window);
    const end = Math.min(totalPages, page + window);
    if (start > 1) {
      result.push(1);
      if (start > 2) result.push("…");
    }
    for (let p = start; p <= end; p++) result.push(p);
    if (end < totalPages) {
      if (end < totalPages - 1) result.push("…");
      result.push(totalPages);
    }
    return result;
  }, [page, totalPages]);

  if (totalPages <= 1) {
    return (
      <nav
        aria-label={label}
        className={cn("flex items-center justify-between text-sm text-muted-foreground", className)}
      >
        <span>
          {total === 0
            ? "No items"
            : `${formatNumber(from)}–${formatNumber(to)} of ${formatNumber(total)}`}
        </span>
      </nav>
    );
  }

  return (
    <nav
      aria-label={label}
      className={cn("flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between", className)}
    >
      <p className="text-sm text-muted-foreground">
        {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(1)}
          disabled={disabled || page <= 1}
          aria-label="First page"
        >
          <ChevronsLeft className="size-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(page - 1)}
          disabled={disabled || page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" />
        </Button>
        {pages.map((p, i) =>
          p === "…" ? (
            <span
              key={`ellipsis-${i}`}
              className="px-2 text-sm text-muted-foreground"
              aria-hidden
            >
              …
            </span>
          ) : (
            <Button
              key={p}
              variant={p === page ? "default" : "outline"}
              size="icon"
              onClick={() => onPageChange(p)}
              disabled={disabled}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
            >
              {p}
            </Button>
          ),
        )}
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(page + 1)}
          disabled={disabled || page >= totalPages}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(totalPages)}
          disabled={disabled || page >= totalPages}
          aria-label="Last page"
        >
          <ChevronsRight className="size-4" />
        </Button>
      </div>
    </nav>
  );
}
