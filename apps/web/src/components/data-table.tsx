/**
 * DataTable — server-side paginated table with sticky header, optional
 * frozen leading column, skeleton loading, and empty/error states.
 *
 * Built on @tanstack/react-table for column defs and sorting, but renders
 * a plain table for full control over styling and virtualization hooks.
 */
import * as React from "react";
import { cn, Skeleton, Pagination } from "@soymutdb/ui";
import { ArrowUpDown, Inbox } from "lucide-react";

export interface DataTableColumn<T> {
  id: string;
  header: string;
  /** Render a cell for the row. */
  cell: (row: T) => React.ReactNode;
  /** Sortable column key (sent to the server). */
  sortKey?: string;
  /** Freeze this column to the left (max 1 recommended). */
  frozen?: boolean;
  /** Right-align numeric columns. */
  numeric?: boolean;
  /** Optional class for the cell. */
  className?: string;
  /** Optional width hint. */
  width?: string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  data: T[];
  /** Loading state — renders skeleton rows. */
  loading?: boolean;
  /** Number of skeleton rows to show while loading (default 8). */
  skeletonRows?: number;
  /** Empty state message. */
  emptyTitle?: string;
  emptyDescription?: string;
  /** Pagination props. Omit to hide pagination. */
  pagination?: {
    page: number;
    totalPages: number;
    total: number;
    pageSize: number;
    onPageChange: (page: number) => void;
  };
  /** Current sort key + direction. */
  sort?: { key: string; dir: "asc" | "desc" } | null;
  /** Sort change handler. */
  onSortChange?: (sort: { key: string; dir: "asc" | "desc" } | null) => void;
  /** Row click handler. */
  onRowClick?: (row: T) => void;
  /** Accessible label for the table. */
  ariaLabel?: string;
  className?: string;
}

export function DataTable<T>({
  columns,
  data,
  loading = false,
  skeletonRows = 8,
  emptyTitle = "No results found",
  emptyDescription = "Try adjusting your filters or search query.",
  pagination,
  sort,
  onSortChange,
  onRowClick,
  ariaLabel,
  className,
}: DataTableProps<T>) {
  const handleSort = (col: DataTableColumn<T>) => {
    if (!col.sortKey || !onSortChange) return;
    if (sort?.key === col.sortKey) {
      onSortChange(sort.dir === "asc" ? { key: col.sortKey, dir: "desc" } : null);
    } else {
      onSortChange({ key: col.sortKey, dir: "asc" });
    }
  };

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full border-collapse text-sm" aria-label={ariaLabel}>
          <thead className="sticky top-0 z-10 bg-muted/60 backdrop-blur">
            <tr className="border-b">
              {columns.map((col) => {
                const isSorted = sort?.key === col.sortKey;
                return (
                  <th
                    key={col.id}
                    scope="col"
                    className={cn(
                      "px-4 py-3 text-left font-medium text-muted-foreground",
                      col.numeric && "text-right",
                      col.frozen && "sticky left-0 z-20 bg-muted/60 backdrop-blur",
                      col.sortKey && "cursor-pointer select-none",
                      col.className,
                    )}
                    style={{ width: col.width }}
                    aria-sort={isSorted ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {col.sortKey ? (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex items-center gap-1 transition-colors hover:text-foreground",
                          col.numeric && "flex-row-reverse",
                          isSorted && "text-foreground",
                        )}
                        onClick={() => handleSort(col)}
                      >
                        {col.header}
                        <ArrowUpDown className="size-3 opacity-60" aria-hidden />
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: skeletonRows }).map((_, ri) => (
                <tr key={`skel-${ri}`} className="border-b last:border-0">
                  {columns.map((col) => (
                    <td
                      key={col.id}
                      className={cn(
                        "px-4 py-3",
                        col.numeric && "text-right",
                        col.frozen && "sticky left-0 z-10 bg-card",
                      )}
                    >
                      <Skeleton className="h-4 w-full max-w-[120px]" />
                    </td>
                  ))}
                </tr>
              ))
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12">
                  <div className="flex flex-col items-center gap-3 text-center">
                    <div className="flex size-10 items-center justify-center rounded-full bg-muted">
                      <Inbox className="size-5 text-muted-foreground" aria-hidden />
                    </div>
                    <p className="font-medium">{emptyTitle}</p>
                    <p className="max-w-sm text-sm text-muted-foreground">{emptyDescription}</p>
                  </div>
                </td>
              </tr>
            ) : (
              data.map((row, ri) => (
                <tr
                  key={ri}
                  className={cn(
                    "border-b last:border-0 transition-colors hover:bg-accent/40",
                    onRowClick && "cursor-pointer",
                  )}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((col) => (
                    <td
                      key={col.id}
                      className={cn(
                        "px-4 py-3 align-middle",
                        col.numeric && "text-right font-mono tabular-nums",
                        col.frozen && "sticky left-0 z-10 bg-card",
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {pagination ? (
        <Pagination
          page={pagination.page}
          totalPages={pagination.totalPages}
          total={pagination.total}
          pageSize={pagination.pageSize}
          onPageChange={pagination.onPageChange}
          disabled={loading}
        />
      ) : null}
    </div>
  );
}
