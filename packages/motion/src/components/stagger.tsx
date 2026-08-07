import * as React from "react";
import { cn } from "../utils";
import { gsap } from "../gsap-setup";
import { useMotion } from "../context";
import { type RevealVariant, FROM_VARS } from "../types";

export interface StaggerProps extends React.HTMLAttributes<HTMLDivElement> {
    baseDelay?: number;
    step?: number;
    once?: boolean;
    variant?: RevealVariant;
    /** ScrollTrigger start position (default: 'top 85%'). */
    start?: string;
    /** Enable fastScrollEnd for performance (default: true). */
    fastScrollEnd?: boolean;
    /** Prevent overlapping animations (default: true). */
    preventOverlaps?: boolean;
}

/**
 * Stagger container — direct children animate in sequence with GSAP. Each
 * child is wrapped in a `data-stagger-item` div so ScrollTrigger + stagger
 * can target them as a group. Honors reduced motion (renders children as-is).
 *
 * Performance: uses fastScrollEnd + preventOverlaps to avoid animation
 * buildup during fast scrolls. will-change is applied sparingly only
 * during animation and cleared on complete via clearProps.
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
    const { stagger: defaultStep, reduced, duration: contextDuration } = useMotion();
    const actualStep = step ?? defaultStep;
    const containerRef = React.useRef<HTMLDivElement | null>(null);

    React.useEffect(() => {
        if (reduced) return;
        const el = containerRef.current;
        if (!el) return;

        const items = el.querySelectorAll<HTMLElement>(":scope > [data-stagger-item]");
        if (items.length === 0) return;

        const ctx = gsap.context(() => {
            const mm = gsap.matchMedia();
            mm.add("(prefers-reduced-motion: no-preference)", () => {
                gsap.fromTo(
                    items,
                    FROM_VARS[variant] ?? FROM_VARS["fade-up"],
                    {
                        opacity: 1,
                        y: 0,
                        x: 0,
                        scale: 1,
                        filter: "blur(0px)",
                        duration: Math.max(0.2, contextDuration / 1000),
                        ease:
                            variant === "scale-in" || variant === "blur-up"
                                ? "back.out(1.4)"
                                : "power2.out",
                        stagger: actualStep / 1000,
                        delay: baseDelay / 1000,
                        scrollTrigger: {
                            trigger: el,
                            start,
                            once,
                            fastScrollEnd,
                            preventOverlaps,
                            toggleActions: "play none none none",
                        },
                        clearProps: "transform,opacity,filter,willChange",
                        overwrite: "auto",
                    },
                );
            });
            return () => mm.revert();
        }, el);

        return () => ctx.revert();
    }, [baseDelay, actualStep, once, reduced, variant, start, fastScrollEnd, preventOverlaps, contextDuration]);

    const childArray = React.Children.toArray(children);

    return (
        <div ref={containerRef} className={cn(className)} style={style} {...rest}>
            {reduced
                ? children
                : childArray.map((child, index) => (
                      <div key={index} data-stagger-item style={{ willChange: "opacity, transform" }}>
                          {child}
                      </div>
                  ))}
        </div>
    );
}
