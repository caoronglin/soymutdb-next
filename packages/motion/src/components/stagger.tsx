import * as React from "react";
import { cn } from "../utils";
import { useMotion } from "../context";
import { type RevealVariant } from "../types";
import { useReveal } from "../use-reveal";

export interface StaggerProps extends React.HTMLAttributes<HTMLDivElement> {
    baseDelay?: number;
    step?: number;
    once?: boolean;
    variant?: RevealVariant;
    /** Legacy viewport start hint retained for source compatibility. */
    start?: string;
    /** Enable fastScrollEnd for performance (default: true). */
    fastScrollEnd?: boolean;
    /** Prevent overlapping animations (default: true). */
    preventOverlaps?: boolean;
}

/**
 * Stagger container — direct children reveal in sequence with bounded CSS
 * opacity/transform transitions driven by one IntersectionObserver.
 */
export function Stagger({
    baseDelay = 0,
    step,
    once = true,
    variant = "fade-up",
    start = "top 85%",
    fastScrollEnd = true,
    preventOverlaps = true,
    className,
    style,
    children,
    ...rest
}: StaggerProps) {
    const { stagger: defaultStep, reduced } = useMotion();
    const actualStep = step ?? defaultStep;
    const containerRef = useReveal<HTMLDivElement>({
        variant,
        delay: baseDelay,
        once,
        stagger: actualStep / 1000,
        childSelector: ":scope > [data-stagger-item]",
    });
    void start;
    void fastScrollEnd;
    void preventOverlaps;

    const childArray = React.Children.toArray(children);

    return (
        <div ref={containerRef} className={cn(className)} style={style} {...rest}>
            {reduced
                ? children
                : childArray.map((child, index) => (
                      <div key={index} data-stagger-item>
                          {child}
                      </div>
                  ))}
        </div>
    );
}
