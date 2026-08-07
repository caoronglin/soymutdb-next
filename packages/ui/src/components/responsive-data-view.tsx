import * as React from "react";
import { cn } from "../lib/utils";
import { EmptyState, type EmptyStateMode } from "./empty-state";
import { ErrorState } from "./error-state";
import { LoadingState } from "./loading-state";

export type ResponsiveDataViewStatus = "loading" | "error" | "empty" | "ready";

export interface ResponsiveDataViewProps {
  /** Current view status. */
  status: ResponsiveDataViewStatus;
  /** Error detail used by the default error view. */
  error?: string | null;
  /** Retry callback used by the default error view. */
  onRetry?: () => void;
  /** Custom loading view (default: LoadingState). */
  loadingView?: React.ReactNode;
  /** Custom error view (default: ErrorState). */
  errorView?: React.ReactNode;
  /** Custom empty view (default: EmptyState). */
  emptyView?: React.ReactNode;
  /** Empty state title. */
  emptyTitle?: string;
  /** Empty state description. */
  emptyDescription?: string;
  /** Empty state copy mode. */
  emptyMode?: EmptyStateMode;
  /** Minimum height of the slot area so views don't jump (e.g. "320px"). */
  minHeight?: string;
  /** Ready view — the actual content. */
  children: React.ReactNode;
  className?: string;
}

/**
 * Status-driven view switcher: takes loading/error/empty/ready statuses and
 * renders the matching slot, with mobile-first defaults that never overflow
 * the viewport. Ready content is rendered as-is.
 */
export function ResponsiveDataView({
  status,
  error,
  onRetry,
  loadingView,
  errorView,
  emptyView,
  emptyTitle,
  emptyDescription,
  emptyMode,
  minHeight,
  children,
  className,
}: ResponsiveDataViewProps) {
  if (status === "ready") {
    return <div className={cn("w-full", className)}>{children}</div>;
  }

  let slot: React.ReactNode;
  if (status === "loading") {
    slot = loadingView ?? <LoadingState />;
  } else if (status === "error") {
    slot = errorView ?? <ErrorState message={error ?? undefined} onRetry={onRetry} />;
  } else {
    slot = emptyView ?? <EmptyState title={emptyTitle} description={emptyDescription} mode={emptyMode} />;
  }

  return (
    <div
      className={cn("flex w-full items-center justify-center py-6", className)}
      style={minHeight ? { minHeight } : undefined}
    >
      {slot}
    </div>
  );
}
