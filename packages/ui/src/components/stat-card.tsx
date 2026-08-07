import * as React from "react";
import { cn } from "../lib/utils";
import { Card, CardContent } from "./card";

interface StatCardProps {
  /** Card label / title text. */
  label: string;
  /** Primary value — can be a number, formatted string, or React node. */
  value: React.ReactNode;
  /** Optional icon element. */
  icon?: React.ReactNode;
  /** Optional trend indicator. */
  trend?: { value: string; positive: boolean };
  className?: string;
}

function StatCard({ label, value, icon, trend, className }: StatCardProps) {
  return (
    <Card className={cn("card-lift card-hover-accent group/stat", className)}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          {icon && (
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/60 text-accent-foreground transition-colors group-hover/stat:bg-primary/10 group-hover/stat:text-primary">
              {icon}
            </div>
          )}
        </div>
        <p className="mt-2 font-display text-2xl font-semibold tabular-nums tracking-tight md:text-[1.75rem]">
          {value}
        </p>
        {trend && (
          <p
            className={cn(
              "mt-1.5 inline-flex items-center gap-1 text-xs font-medium",
              trend.positive ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400",
            )}
          >
            <span>{trend.positive ? "↑" : "↓"}</span>
            <span>{trend.value}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export { StatCard, type StatCardProps };
