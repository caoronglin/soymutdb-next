import * as React from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  Columns3,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "./table";
import { Pagination } from "./pagination";
import { Skeleton } from "./skeleton";
import { EmptyState, type EmptyStateMode } from "./empty-state";
import { ErrorState } from "./error-state";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DataTableColumn<T> {
  /** Unique column key. */
  key: string;
  /** Header label. */
  header: React.ReactNode;
  /** Accessible label for the sort button (defaults to the plain-text header). */
  ariaLabel?: string;
  /** Render the cell value for a row. */
  cell: (row: T) => React.ReactNode;
  /** Whether this column is sortable. */
  sortable?: boolean;
  /** Sort accessor — defaults to `row[key]`. */
  sortAccessor?: (row: T) => string | number | Date | null | undefined;
  /** Optional className for cells in this column. */
  className?: string;
  /** Header/cell alignment. */
  align?: "left" | "center" | "right";
  /** In responsive card mode, use this column as the card heading. */
  primary?: boolean;
}

export type DataTableSort = { key: string; dir: "asc" | "desc" } | null;

export interface DataTableSelection {
  /** Currently selected row keys (values returned by `rowKey`). */
  selectedKeys: string[];
  /** Called with the new selection whenever it changes. */
  onSelectionChange: (keys: string[]) => void;
}

export interface DataTableColumnVisibility {
  /** Keys of columns currently hidden. */
  hiddenKeys: string[];
  /** Called when a column's visibility is toggled. */
  onToggle: (key: string, visible: boolean) => void;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  data: T[];
  /** Row key accessor. */
  rowKey: (row: T) => string;
  /** Loading state — renders skeleton rows by default. */
  loading?: boolean;
  /** Error message — renders an ErrorState by default. */
  error?: string | null;
  /** Retry callback shown in the default error view. */
  onRetry?: () => void;
  /** Number of skeleton rows while loading (default 5). */
  skeletonRows?: number;
  /** Custom loading slot. */
  loadingSlot?: React.ReactNode;
  /** Custom error slot. */
  errorSlot?: React.ReactNode;
  /** Custom empty slot. */
  emptySlot?: React.ReactNode;
  /** Empty state title. */
  emptyTitle?: string;
  /** Empty state description. */
  emptyDescription?: string;
  /** Empty state copy mode ("no data" vs "filtered"). */
  emptyMode?: EmptyStateMode;
  /** Empty state icon. */
  emptyIcon?: LucideIcon;
  /** Current page (1-based) — together with pageSize/total/onPageChange enables pagination. */
  page?: number;
  /** Items per page. */
  pageSize?: number;
  /** Total item count (server-side total, not `data.length`). */
  total?: number;
  /** Page change handler. */
  onPageChange?: (page: number) => void;
  /**
   * Controlled sort state. When `onSortChange` is provided the component is
   * controlled: the data is assumed to be sorted upstream (e.g. server-side)
   * and only the indicator/state is managed here.
   */
  sort?: DataTableSort;
  /** Sort change handler — enables controlled sorting. */
  onSortChange?: (sort: DataTableSort) => void;
  /** Optional row click handler. */
  onRowClick?: (row: T) => void;
  /** Optional row selection. */
  selection?: DataTableSelection;
  /** Optional column visibility control. */
  columnVisibility?: DataTableColumnVisibility;
  /** Optional toolbar rendered above the table (next to the columns menu). */
  toolbar?: React.ReactNode;
  /** Accessible label for the table. */
  ariaLabel?: string;
  /** Optional row label used for accessible names (defaults to "Row N"). */
  getRowLabel?: (row: T) => string;
  /** Mobile degradation: render compact cards below `md` instead of a table. */
  responsive?: boolean;
  /** Accessible label for the pagination region. */
  paginationLabel?: string;
  className?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Best-effort plain-text extraction from a ReactNode (for aria labels). */
function plainText(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(plainText).join(" ");
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode };
    return plainText(props.children);
  }
  return "";
}

function compareValues(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime();
  const sa = a === null || a === undefined ? "" : String(a);
  const sb = b === null || b === undefined ? "" : String(b);
  return sa.localeCompare(sb, undefined, { numeric: true, sensitivity: "base" });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Type-safe data table with sorting, pagination, optional row selection,
 * optional column visibility control, keyboard navigation, and mobile
 * degradation to compact cards. No API calls — data flows in via props.
 *
 * Keyboard: rows are focusable when `onRowClick` or `selection` is set;
 * ArrowUp/ArrowDown/Home/End move between rows, Enter activates the row,
 * Space toggles selection (or activates when selection is disabled).
 */
export function DataTable<T>({
  columns,
  data,
  rowKey,
  loading = false,
  error = null,
  onRetry,
  skeletonRows = 5,
  loadingSlot,
  errorSlot,
  emptySlot,
  emptyTitle,
  emptyDescription,
  emptyMode,
  emptyIcon,
  page,
  pageSize,
  total,
  onPageChange,
  sort: controlledSort,
  onSortChange,
  onRowClick,
  selection,
  columnVisibility,
  toolbar,
  ariaLabel = "Data table",
  getRowLabel,
  responsive = false,
  paginationLabel = "Table pagination",
  className,
}: DataTableProps<T>) {
  const isSortControlled = onSortChange !== undefined;
  const [internalSort, setInternalSort] = React.useState<DataTableSort>(null);
  const sort = isSortControlled ? (controlledSort ?? null) : internalSort;

  const handleSortToggle = React.useCallback(
    (col: DataTableColumn<T>) => {
      if (!col.sortable) return;
      const next: DataTableSort =
        sort?.key === col.key
          ? sort.dir === "asc"
            ? { key: col.key, dir: "desc" }
            : null
          : { key: col.key, dir: "asc" };
      if (isSortControlled) onSortChange(next);
      else setInternalSort(next);
    },
    [sort, isSortControlled, onSortChange],
  );

  // Client-side sorting only applies in uncontrolled mode — controlled mode
  // assumes the data is already sorted upstream (e.g. server-side).
  const displayData = React.useMemo(() => {
    if (isSortControlled || !sort) return data;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortable) return data;
    const accessor =
      col.sortAccessor ??
      ((row: T) =>
        (row as Record<string, unknown>)[col.key] as
          | string
          | number
          | Date
          | null
          | undefined);
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...data].sort((a, b) => compareValues(accessor(a), accessor(b)) * factor);
  }, [data, columns, sort, isSortControlled]);

  const hiddenKeys = columnVisibility?.hiddenKeys ?? [];
  const visibleColumns = React.useMemo(
    () => columns.filter((c) => !hiddenKeys.includes(c.key)),
    [columns, hiddenKeys],
  );
  const colSpan = visibleColumns.length + (selection ? 1 : 0);

  const paginationProps =
    page !== undefined && pageSize !== undefined && total !== undefined && onPageChange
      ? { page, pageSize, total, onPageChange }
      : null;
  const totalPages = paginationProps
    ? Math.max(1, Math.ceil(paginationProps.total / paginationProps.pageSize))
    : 1;

  // --- Row selection ------------------------------------------------------

  const visibleKeys = React.useMemo(
    () => displayData.map((row) => rowKey(row)),
    [displayData, rowKey],
  );
  const allVisibleSelected =
    visibleKeys.length > 0 &&
    visibleKeys.every((k) => selection?.selectedKeys.includes(k) ?? false);
  const someVisibleSelected =
    !allVisibleSelected &&
    visibleKeys.some((k) => selection?.selectedKeys.includes(k) ?? false);

  const selectAllRef = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someVisibleSelected;
  }, [someVisibleSelected]);

  const toggleAllVisible = React.useCallback(() => {
    if (!selection) return;
    const next = allVisibleSelected
      ? selection.selectedKeys.filter((k) => !visibleKeys.includes(k))
      : Array.from(new Set([...selection.selectedKeys, ...visibleKeys]));
    selection.onSelectionChange(next);
  }, [selection, allVisibleSelected, visibleKeys]);

  const toggleRow = React.useCallback(
    (row: T) => {
      if (!selection) return;
      const key = rowKey(row);
      const selected = selection.selectedKeys.includes(key);
      const next = selected
        ? selection.selectedKeys.filter((k) => k !== key)
        : [...selection.selectedKeys, key];
      selection.onSelectionChange(next);
    },
    [selection, rowKey],
  );

  // --- Keyboard navigation (roving row focus) ------------------------------

  const [focusedRow, setFocusedRow] = React.useState<number | null>(null);
  const tableRowRefs = React.useRef<(HTMLElement | null)[]>([]);
  const cardRowRefs = React.useRef<(HTMLElement | null)[]>([]);
  const interactive = Boolean(onRowClick || selection);

  const handleRowKeyDown = React.useCallback(
    (
      e: React.KeyboardEvent<HTMLElement>,
      index: number,
      row: T,
      refs: React.MutableRefObject<(HTMLElement | null)[]>,
    ) => {
      // Let interactive children (checkboxes, links, buttons) handle their own keys.
      if (e.target !== e.currentTarget) return;
      if (
        e.key === "ArrowDown" ||
        e.key === "ArrowUp" ||
        e.key === "Home" ||
        e.key === "End"
      ) {
        e.preventDefault();
        const rows = refs.current;
        if (rows.length === 0) return;
        let next: number;
        if (e.key === "ArrowDown") next = Math.min(index + 1, rows.length - 1);
        else if (e.key === "ArrowUp") next = Math.max(index - 1, 0);
        else if (e.key === "Home") next = 0;
        else next = rows.length - 1;
        setFocusedRow(next);
        rows[next]?.focus();
      } else if (e.key === "Enter") {
        onRowClick?.(row);
      } else if (e.key === " ") {
        e.preventDefault();
        if (selection) toggleRow(row);
        else onRowClick?.(row);
      }
    },
    [onRowClick, selection, toggleRow],
  );

  const rowTabIndex = (i: number): number | undefined =>
    interactive
      ? focusedRow === null
        ? i === 0
          ? 0
          : -1
        : focusedRow === i
          ? 0
          : -1
      : undefined;

  const rowLabel = (row: T, i: number): string =>
    getRowLabel?.(row) ?? `Row ${i + 1}`;

  // --- Render helpers -------------------------------------------------------

  const renderHeaderRow = () => (
    <TableRow className="bg-muted/40 hover:bg-muted/40">
      {selection ? (
        <TableHead className="w-10">
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allVisibleSelected}
            onChange={toggleAllVisible}
            aria-label="Select all rows"
            className="size-4 accent-[var(--primary)]"
          />
        </TableHead>
      ) : null}
      {visibleColumns.map((col) => {
        const isSorted = sort?.key === col.key;
        return (
          <TableHead
            key={col.key}
            className={cn(
              col.align === "right" && "text-right",
              col.align === "center" && "text-center",
              col.className,
            )}
            aria-sort={
              isSorted
                ? sort?.dir === "asc"
                  ? "ascending"
                  : "descending"
                : undefined
            }
          >
            {col.sortable ? (
              <button
                type="button"
                onClick={() => handleSortToggle(col)}
                aria-label={`Sort by ${col.ariaLabel ?? (plainText(col.header) || col.key)}`}
                className="inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {col.header}
                {isSorted ? (
                  sort?.dir === "asc" ? (
                    <ArrowUp className="size-3.5" aria-hidden />
                  ) : (
                    <ArrowDown className="size-3.5" aria-hidden />
                  )
                ) : (
                  <ArrowUpDown className="size-3.5 opacity-40" aria-hidden />
                )}
              </button>
            ) : (
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {col.header}
              </span>
            )}
          </TableHead>
        );
      })}
    </TableRow>
  );

  const renderTableBody = () => {
    if (error) {
      return (
        <TableRow>
          <TableCell colSpan={colSpan} className="p-0">
            {errorSlot ?? (
              <ErrorState message={error} onRetry={onRetry} className="rounded-none border-0" />
            )}
          </TableCell>
        </TableRow>
      );
    }
    if (loading) {
      return (
        <>
          {loadingSlot ??
            Array.from({ length: skeletonRows }, (_, i) => (
              <TableRow key={`skeleton-${i}`} aria-hidden>
                {selection ? (
                  <TableCell>
                    <Skeleton className="size-4" />
                  </TableCell>
                ) : null}
                {visibleColumns.map((col) => (
                  <TableCell key={col.key}>
                    <Skeleton className="h-5 w-full max-w-32" />
                  </TableCell>
                ))}
              </TableRow>
            ))}
        </>
      );
    }
    if (displayData.length === 0) {
      return (
        <TableRow>
          <TableCell colSpan={colSpan} className="p-0">
            {emptySlot ?? (
              <EmptyState
                icon={emptyIcon}
                title={emptyTitle}
                description={emptyDescription}
                mode={emptyMode}
                className="rounded-none border-0"
              />
            )}
          </TableCell>
        </TableRow>
      );
    }
    return (
      <>
        {displayData.map((row, i) => {
          const key = rowKey(row);
          const selected = selection?.selectedKeys.includes(key) ?? false;
          return (
            <TableRow
              key={key}
              ref={(el) => {
                tableRowRefs.current[i] = el;
              }}
              tabIndex={rowTabIndex(i)}
              onFocus={() => setFocusedRow(i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={(e) => handleRowKeyDown(e, i, row, tableRowRefs)}
              data-state={selected ? "selected" : undefined}
              className={cn(onRowClick && "cursor-pointer")}
            >
              {selection ? (
                <TableCell>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleRow(row)}
                    aria-label={`Select ${rowLabel(row, i)}`}
                    className="size-4 accent-[var(--primary)]"
                  />
                </TableCell>
              ) : null}
              {visibleColumns.map((col) => (
                <TableCell
                  key={col.key}
                  className={cn(
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center",
                    col.className,
                  )}
                >
                  {col.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          );
        })}
      </>
    );
  };

  const primaryColumn =
    visibleColumns.find((c) => c.primary) ?? visibleColumns[0];

  const renderCardBody = () => {
    if (error) {
      return (
        errorSlot ?? (
          <ErrorState message={error} onRetry={onRetry} />
        )
      );
    }
    if (loading) {
      return (
        loadingSlot ?? (
          <div className="space-y-3" aria-hidden>
            {Array.from({ length: skeletonRows }, (_, i) => (
              <div key={`card-skeleton-${i}`} className="rounded-xl border border-border bg-card p-4">
                <Skeleton className="h-5 w-2/3" />
                <div className="mt-3 space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/4" />
                </div>
              </div>
            ))}
          </div>
        )
      );
    }
    if (displayData.length === 0) {
      return (
        emptySlot ?? (
          <EmptyState
            icon={emptyIcon}
            title={emptyTitle}
            description={emptyDescription}
            mode={emptyMode}
          />
        )
      );
    }
    return (
      <ul aria-label={`${ariaLabel} (compact view)`} className="space-y-3">
        {displayData.map((row, i) => {
          const key = rowKey(row);
          const selected = selection?.selectedKeys.includes(key) ?? false;
          return (
            <li key={key}>
              <div
                ref={(el) => {
                  cardRowRefs.current[i] = el;
                }}
                tabIndex={rowTabIndex(i)}
                onFocus={() => setFocusedRow(i)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={(e) => handleRowKeyDown(e, i, row, cardRowRefs)}
                aria-label={rowLabel(row, i)}
                data-state={selected ? "selected" : undefined}
                className={cn(
                  "rounded-xl border bg-card p-4 shadow-sm transition-colors",
                  selected ? "border-primary/40 bg-primary/5" : "border-border",
                  onRowClick && "cursor-pointer",
                )}
              >
                <div className="flex items-start gap-3">
                  {selection ? (
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleRow(row)}
                      aria-label={`Select ${rowLabel(row, i)}`}
                      className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
                    />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    {primaryColumn ? (
                      <div className="truncate text-sm font-medium">
                        {primaryColumn.cell(row)}
                      </div>
                    ) : null}
                    {visibleColumns.filter((c) => c !== primaryColumn).length > 0 ? (
                      <dl className="mt-2 space-y-1.5">
                        {visibleColumns
                          .filter((c) => c !== primaryColumn)
                          .map((col) => (
                            <div key={col.key} className="flex items-baseline justify-between gap-3">
                              <dt className="shrink-0 text-xs text-muted-foreground">
                                {col.header}
                              </dt>
                              <dd className="truncate text-right text-sm">
                                {col.cell(row)}
                              </dd>
                            </div>
                          ))}
                      </dl>
                    ) : null}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    );
  };

  const showToolbar = toolbar !== undefined || columnVisibility !== undefined;

  return (
    <div
      className={cn("flex flex-col gap-4", className)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setFocusedRow(null);
        }
      }}
    >
      {showToolbar ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {toolbar ? <div className="flex flex-wrap items-center gap-2">{toolbar}</div> : null}
          {columnVisibility ? (
            <div className={cn("relative", toolbar ? "" : "ml-auto")}>
              <details className="group relative">
                <summary className="inline-flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-md border border-input bg-background/50 px-3 text-xs font-medium text-muted-foreground shadow-sm transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
                  <Columns3 className="size-3.5" aria-hidden />
                  Columns
                  <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <div className="absolute right-0 z-30 mt-1 w-56 rounded-md border border-border bg-popover p-1.5 shadow-lg">
                  {columns.map((col) => {
                    const visible = !columnVisibility.hiddenKeys.includes(col.key);
                    return (
                      <label
                        key={col.key}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
                      >
                        <input
                          type="checkbox"
                          checked={visible}
                          onChange={(e) => columnVisibility.onToggle(col.key, e.target.checked)}
                          className="size-4 accent-[var(--primary)]"
                        />
                        <span className="truncate">{col.header}</span>
                      </label>
                    );
                  })}
                </div>
              </details>
            </div>
          ) : null}
        </div>
      ) : null}

      {responsive ? (
        <div className="md:hidden">{renderCardBody()}</div>
      ) : null}

      <div className={cn("rounded-xl border border-border bg-card", responsive && "hidden md:block")}>
        <Table aria-label={ariaLabel}>
          <TableHeader>{renderHeaderRow()}</TableHeader>
          <TableBody>{renderTableBody()}</TableBody>
        </Table>
      </div>

      {paginationProps ? (
        <Pagination
          page={paginationProps.page}
          totalPages={totalPages}
          total={paginationProps.total}
          pageSize={paginationProps.pageSize}
          onPageChange={paginationProps.onPageChange}
          disabled={loading}
          label={paginationLabel}
        />
      ) : null}
    </div>
  );
}
