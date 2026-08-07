import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-wide transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground shadow-sm",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground shadow-sm",
        outline: "text-foreground",
        success:
          "border-transparent bg-[oklch(0.90_0.08_151)] text-[oklch(0.30_0.10_151)] dark:bg-[oklch(0.30_0.05_151)] dark:text-[oklch(0.85_0.10_151)]",
        warning:
          "border-transparent bg-[oklch(0.92_0.07_75)] text-[oklch(0.34_0.09_75)] dark:bg-[oklch(0.30_0.06_75)] dark:text-[oklch(0.85_0.10_75)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof badgeVariants>) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
