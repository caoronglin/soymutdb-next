import * as React from "react";
import { cn } from "../lib/utils";

/**
 * Standardised Card component system.
 *
 * Design spec (refined):
 * - Subtle layered shadow, hairline border
 * - Rounded corners (--radius = 0.625rem / 10px)
 * - Hover-lift via `.card-lift` utility in global CSS
 * - Gradient top-accent on hover via `.card-hover-accent`
 *
 * Responsive: Cards fill their grid container; parent grids control
 * breakpoint layout (1-col <768px, 2-col 768–1024px, 4-col >1024px).
 */

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "group/card relative overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        className,
      )}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex min-h-10 flex-col gap-1.5 border-b border-border/60 bg-muted/20 px-5 py-3",
        className,
      )}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      className={cn(
        "text-base font-semibold leading-none tracking-tight text-card-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("p-5 [&>*+*]:mt-2", className)}
      {...props}
    />
  );
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex items-center px-5 py-4", className)}
      {...props}
    />
  );
}

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
