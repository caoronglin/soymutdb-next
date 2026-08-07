/**
 * FilterPanel — collapsible sidebar of filter controls for list pages.
 * Renders labeled groups of controls; the parent owns the filter state.
 */
import * as React from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { cn, Button } from "@soymutdb/ui";

export interface FilterGroup {
  id: string;
  label: string;
  /** Render the control(s) for this group. */
  children: React.ReactNode;
}

export interface FilterPanelProps {
  groups: FilterGroup[];
  /** Active filter count (shown as a badge). */
  activeCount?: number;
  /** Reset handler. */
  onReset?: () => void;
  className?: string;
  /** Collapsible on mobile (default true). */
  collapsible?: boolean;
}

export function FilterPanel({
  groups,
  activeCount = 0,
  onReset,
  className,
  collapsible = true,
}: FilterPanelProps) {
  const [open, setOpen] = React.useState(!collapsible);

  return (
    <aside className={cn("w-full lg:w-64 lg:shrink-0", className)} aria-label="Filters">
      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex items-center justify-between gap-2 border-b bg-muted/30 p-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
            <h2 className="font-display text-sm font-semibold">Filters</h2>
            {activeCount > 0 ? (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1.5 font-mono text-[10px] font-semibold text-primary">
                {activeCount}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-1">
            {onReset ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={onReset}
                disabled={activeCount === 0}
                className="h-7 px-2 text-xs"
              >
                <X className="size-3" aria-hidden />
                Reset
              </Button>
            ) : null}
            {collapsible ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs lg:hidden"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
              >
                {open ? "Hide" : "Show"}
              </Button>
            ) : null}
          </div>
        </div>
        <div className={cn("p-4", collapsible && !open && "hidden lg:block")}>
          <div className="flex flex-col divide-y divide-border/60">
            {groups.map((g) => (
              <div key={g.id} className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
                <label className="eyebrow" htmlFor={g.id}>
                  {g.label}
                </label>
                {g.children}
              </div>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
