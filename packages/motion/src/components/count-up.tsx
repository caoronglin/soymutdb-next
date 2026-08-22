import * as React from "react";
import { cn } from "../utils";

function formatNumber(n: number): string {
    return n.toLocaleString("en-US");
}

export interface CountUpProps extends React.HTMLAttributes<HTMLSpanElement> {
    end: number;
    start?: number;
    duration?: number;
    formatted?: boolean;
    suffix?: string;
    prefix?: string;
}

/**
 * Stable numeric rendering. The former decorative counter is intentionally
 * static so data values are immediately available to users and assistive tech.
 */
export function CountUp({
    end,
    start = 0,
    duration = 1200,
    formatted = true,
    suffix,
    prefix,
    className,
    ...rest
}: CountUpProps) {
    void start;
    void duration;
    const text = formatted ? formatNumber(end) : String(end);

    return (
        <span className={cn("font-mono tabular-nums", className)} data-numeric {...rest}>
            {prefix}
            {text}
            {suffix}
        </span>
    );
}
