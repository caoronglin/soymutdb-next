import * as React from "react";
import { ChevronRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

export interface PageHeaderBreadcrumbItem {
  label: React.ReactNode;
  /** Link target — omit for the current page. */
  href?: string;
}

export interface PageHeaderProps {
  /** Page title. */
  title: React.ReactNode;
  /** Optional supporting description. */
  description?: React.ReactNode;
  /** Optional page icon rendered in a rounded square. */
  icon?: LucideIcon;
  /** Optional breadcrumb trail — an array of items or a custom node. */
  breadcrumb?: PageHeaderBreadcrumbItem[] | React.ReactNode;
  /** Action buttons rendered on the right. */
  actions?: React.ReactNode;
  className?: string;
}

/**
 * Standardised page header with optional breadcrumb, icon, description and
 * action slot. Stacks vertically on mobile, aligns to a row on desktop.
 */
export function PageHeader({
  title,
  description,
  icon: Icon,
  breadcrumb,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-4", className)}>
      {breadcrumb ? (
        Array.isArray(breadcrumb) ? (
          <nav aria-label="Breadcrumb">
            <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
              {breadcrumb.map((item, i) => {
                const isLast = i === breadcrumb.length - 1;
                return (
                  <li key={i} className="flex items-center gap-1.5">
                    {item.href && !isLast ? (
                      <a
                        href={item.href}
                        className="rounded transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      >
                        {item.label}
                      </a>
                    ) : (
                      <span
                        aria-current={isLast ? "page" : undefined}
                        className={cn(!isLast && "text-muted-foreground")}
                      >
                        {item.label}
                      </span>
                    )}
                    {!isLast ? (
                      <ChevronRight className="size-3.5 text-muted-foreground/60" aria-hidden />
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </nav>
        ) : (
          breadcrumb
        )
      ) : null}

      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3.5">
          {Icon ? (
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-primary shadow-sm">
              <Icon className="size-5" aria-hidden />
            </div>
          ) : null}
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
              {title}
            </h1>
            {description ? (
              <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2 lg:shrink-0">{actions}</div>
        ) : null}
      </div>
    </header>
  );
}
