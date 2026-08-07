import * as React from "react";
import { ChevronDown, ListFilter, RotateCcw } from "lucide-react";
import { cn } from "../lib/utils";
import { Badge } from "./badge";

export interface FilterItem {
  /** Unique filter key. */
  key: string;
  /** Filter label. */
  label: React.ReactNode;
  /** Filter control (input, select, ...). */
  control: React.ReactNode;
  /** Whether the filter currently has an active value. */
  active?: boolean;
  /** Number of active values — shown as a badge (e.g. selected options). */
  count?: number;
}

export interface FilterBarProps {
  /** Filter items rendered in a responsive grid. */
  items: FilterItem[];
  /** Master "any filter active" flag — shows the clear button when set (or when any item is active). */
  active?: boolean;
  /** Clears all filters. */
  onClearAll?: () => void;
  /** Accessible label for the region (default "Filters"). */
  label?: string;
  /** Clear button label (default "Clear all"). */
  clearAllLabel?: string;
  /** Mobile toggle button label (default "Filters"). */
  toggleLabel?: string;
  /** Number of filter columns on desktop (default 4). */
  columns?: 2 | 3 | 4;
  /** Render the mobile collapse toggle (default true). */
  collapsible?: boolean;
  /** Initial collapsed state on mobile (default false). */
  defaultCollapsed?: boolean;
  className?: string;
}

/**
 * Filter bar rendering an array of filter items in a responsive grid.
 * Collapses into a toggleable panel on mobile; shows an active indicator
 * and an optional "clear all" action.
 */
export function FilterBar({
  items,
  active,
  onClearAll,
  label = "Filters",
  clearAllLabel = "Clear all",
  toggleLabel = "Filters",
  columns = 4,
  collapsible = true,
  defaultCollapsed = false,
  className,
}: FilterBarProps) {
  const [open, setOpen] = React.useState(!defaultCollapsed);
  const hasActive = active ?? items.some((item) => item.active);
  const panelId = React.useId();

  const gridClass =
    columns === 2
      ? "sm:grid-cols-2"
      : columns === 3
        ? "sm:grid-cols-2 lg:grid-cols-3"
        : "sm:grid-cols-2 lg:grid-cols-4";

  return (
    <section aria-label={label} className={cn("rounded-xl border border-border bg-card p-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <ListFilter className="size-4 text-muted-foreground" aria-hidden />
          <span>{label}</span>
          {hasActive ? <Badge variant="secondary">Active</Badge> : null}
        </div>

        {collapsible ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={panelId}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-input px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:hidden"
          >
            {toggleLabel}
            <ChevronDown
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </button>
        ) : null}

        {onClearAll && hasActive ? (
          <button
            type="button"
            onClick={onClearAll}
            className="ml-auto inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <RotateCcw className="size-3" aria-hidden />
            {clearAllLabel}
          </button>
        ) : null}
      </div>

      <div
        id={panelId}
        className={cn("mt-3 grid gap-2.5", gridClass, !open && "hidden sm:grid")}
      >
        {items.map((item) => (
          <div
            key={item.key}
            className={cn(
              "flex flex-col gap-1.5 rounded-lg border p-2.5 transition-colors",
              item.active ? "border-primary/40 bg-primary/5" : "border-border bg-background/40",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {item.label}
              </span>
              {item.count != null && item.count > 0 ? (
                <Badge variant={item.active ? "default" : "secondary"}>{item.count}</Badge>
              ) : null}
            </div>
            {item.control}
          </div>
        ))}
      </div>
    </section>
  );
}
