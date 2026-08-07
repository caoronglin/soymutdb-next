import * as React from "react";
import { BarChart3 } from "lucide-react";
import { cn } from "../lib/utils";

export interface ChartEmptyStateProps {
  /** Whether the empty state should be visible. */
  visible: boolean;
  /** Optional custom message — defaults to "暂无数据". */
  message?: string;
  /** Optional secondary description (e.g. error detail). */
  description?: string;
  /** Extra class names for the overlay container. */
  className?: string;
}

/**
 * Standardised empty-data / error placeholder for ECharts containers.
 *
 * Renders as an absolutely-positioned overlay with a smooth fade transition.
 * When `visible` is true the placeholder fades in and intercepts pointer
 * events; when false it fades out and becomes transparent + non-interactive.
 *
 * Visual spec (matches system design tokens):
 * - Icon: BarChart3 in a muted circle (size-12, 48px)
 * - Title: 14px font-semibold, muted-foreground colour
 * - Description: 12px text-muted-foreground
 * - Background: bg-card/80 backdrop-blur for subtle layering
 */
export const ChartEmptyState = React.memo(function ChartEmptyState({
  visible,
  message = "暂无数据",
  description,
  className,
}: ChartEmptyStateProps) {
  return (
    <div
      className={cn(
        "absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-card/80 backdrop-blur-sm transition-opacity duration-300 ease-out",
        visible ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        className,
      )}
      role="status"
      aria-live="polite"
      aria-hidden={!visible}
    >
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <BarChart3 className="size-6 text-muted-foreground" aria-hidden />
      </div>
      <p className="text-sm font-semibold text-muted-foreground">{message}</p>
      {description ? (
        <p className="max-w-xs text-center text-xs text-muted-foreground/70">
          {description}
        </p>
      ) : null}
    </div>
  );
});
