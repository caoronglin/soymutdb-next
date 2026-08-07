import { RotateCcw, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";
import { Button } from "./button";

export interface ErrorStateProps {
  /** Primary heading (default "Something went wrong"). */
  title?: string;
  /** Error detail shown under the heading. */
  message?: string;
  /** Retry callback — renders a retry button when provided. */
  onRetry?: () => void;
  /** Custom retry button label (default "Try again"). */
  retryLabel?: string;
  /** Optional request id shown for support/debugging. */
  requestId?: string;
  /** Lucide icon (default TriangleAlert). */
  icon?: LucideIcon;
  className?: string;
}

/**
 * Error placeholder with message, optional retry action and optional
 * request id for support/debugging.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Try again",
  requestId,
  icon: Icon = TriangleAlert,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-destructive/30 bg-destructive/5 px-8 py-12 text-center",
        className,
      )}
    >
      <div className="mb-4 flex size-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <Icon className="size-7" aria-hidden />
      </div>
      <h3 className="font-display text-lg font-semibold tracking-tight">{title}</h3>
      {message ? (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          {message}
        </p>
      ) : null}
      {requestId ? (
        <p className="mt-3 rounded-md border border-border bg-muted/50 px-2 py-1 font-mono text-[11px] text-muted-foreground">
          Request ID: {requestId}
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-5">
          <RotateCcw className="size-3.5" aria-hidden />
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}
