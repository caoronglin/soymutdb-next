import * as React from "react";
import { SearchX } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

/** Copy variant: "empty" = no records at all, "filtered" = filters matched nothing. */
export type EmptyStateMode = "empty" | "filtered";

export interface EmptyStateProps {
  /** Lucide icon component (defaults to SearchX in "filtered" mode). */
  icon?: LucideIcon;
  /** Primary heading — falls back to the mode default. */
  title?: string;
  /** Supporting description — falls back to the mode default. */
  description?: string;
  /** Copy variant (default "empty"). */
  mode?: EmptyStateMode;
  /** Optional call-to-action rendered in a row. */
  action?: React.ReactNode;
  className?: string;
}

const MODE_COPY: Record<EmptyStateMode, { title: string; description: string }> = {
  empty: {
    title: "No data",
    description: "There are no records to display yet.",
  },
  filtered: {
    title: "No results found",
    description: "Try adjusting your filters or search query.",
  },
};

/**
 * Empty state placeholder for lists, tables, and search results.
 * Friendly, intentional, with soft styling.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  mode = "empty",
  action,
  className,
}: EmptyStateProps) {
  const copy = MODE_COPY[mode];
  const IconComponent = Icon ?? (mode === "filtered" ? SearchX : undefined);
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-muted/20 px-8 py-14 text-center",
        className,
      )}
      role="status"
    >
      {IconComponent ? (
        <div className="mb-5 flex size-14 items-center justify-center rounded-full bg-accent/50 text-accent-foreground/80">
          <IconComponent className="size-7" aria-hidden />
        </div>
      ) : null}
      <h3 className="font-display text-lg font-semibold tracking-tight">
        {title ?? copy.title}
      </h3>
      {description !== undefined || copy.description ? (
        <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
          {description ?? copy.description}
        </p>
      ) : null}
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}
