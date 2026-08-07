import * as React from "react";
import { LoaderCircle } from "lucide-react";
import { cn } from "../lib/utils";
import { Skeleton } from "./skeleton";

export interface LoadingStateProps {
  /** Accessible label / spinner text (default "Loading"). */
  label?: string;
  /** Presentation: skeleton lines (default) or centered spinner. */
  variant?: "skeleton" | "spinner";
  /** Number of skeleton rows (default 3). */
  rows?: number;
  /** Custom skeleton shape rendered per row (default: a single Skeleton line). */
  shape?: React.ReactNode;
  className?: string;
}

/**
 * Loading placeholder. Defaults to a skeleton structure matching the
 * `Skeleton` component; pass `shape` to customise each row or use
 * `variant="spinner"` for a compact spinner.
 */
export function LoadingState({
  label = "Loading",
  variant = "skeleton",
  rows = 3,
  shape,
  className,
}: LoadingStateProps) {
  if (variant === "spinner") {
    return (
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "flex items-center justify-center gap-3 py-12 text-muted-foreground",
          className,
        )}
      >
        <LoaderCircle className="size-5 animate-spin" aria-hidden />
        <span className="text-sm">{label}</span>
      </div>
    );
  }
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={cn("space-y-3 py-2", className)}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          {shape ?? <Skeleton className="h-5 w-full" />}
        </div>
      ))}
    </div>
  );
}
