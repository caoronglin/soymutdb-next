import * as React from "react";
import { FlaskConical } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

export interface DemoStateProps {
  /** Banner heading (default "Demo mode"). */
  title?: string;
  /** Supporting description. */
  description?: React.ReactNode;
  /** Extra content (badges, links, buttons) rendered inline on the right. */
  children?: React.ReactNode;
  /** Lucide icon (default FlaskConical). */
  icon?: LucideIcon;
  className?: string;
}

/**
 * Demo-mode banner. Prominent but non-blocking: a horizontal strip above
 * content, tinted with the primary token — it never overlays the UI.
 */
export function DemoState({
  title = "Demo mode",
  description,
  children,
  icon: Icon = FlaskConical,
  className,
}: DemoStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-primary/25 bg-primary/5 px-4 py-3 sm:flex-row sm:items-center",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Icon className="size-5" aria-hidden />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">{title}</p>
          {description ? (
            <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>
      {children ? (
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">{children}</div>
      ) : null}
    </div>
  );
}
