/**
 * useGsapReveal — variant-driven scroll reveal powered by GSAP + ScrollTrigger.
 *
 * Returns a ref to attach to the target element. On mount the element is
 * tweened from a hidden variant state into its natural state once it enters
 * the viewport. Honors reduced motion (snaps to the final state immediately).
 *
 * Performance optimizations:
 *   - fastScrollEnd: skips mid-animation if user scrolls past fast
 *   - preventOverlaps: prevents multiple reveals on the same element
 *   - once: true by default to avoid re-triggering
 *   - gsap.context() for automatic cleanup
 *   - matchMedia for prefers-reduced-motion
 */
import * as React from "react";
import { gsap, ScrollTrigger } from "./gsap-setup";
import { useMotion } from "./context";
import { FROM_VARS, type RevealVariant } from "./types";

export interface UseGsapRevealOptions {
    variant?: RevealVariant;
    delay?: number;
    duration?: number;
    once?: boolean;
    /** ScrollTrigger start position (default: 'top 85%'). */
    start?: string;
    /** Enable fastScrollEnd for performance (default: true). */
    fastScrollEnd?: boolean;
    /** Prevent overlapping animations (default: true). */
    preventOverlaps?: boolean;
}

export function useGsapReveal<T extends HTMLElement = HTMLDivElement>(
    options: UseGsapRevealOptions = {},
): React.RefObject<T | null> {
    const {
        variant = "fade-up",
        delay = 0,
        duration,
        once = true,
        start = "top 85%",
        fastScrollEnd = true,
        preventOverlaps = true,
    } = options;
    const ref = React.useRef<T | null>(null);
    const { reduced, duration: contextDuration } = useMotion();

    const effectiveDuration = duration ?? Math.max(0.2, contextDuration / 1000);

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;

        if (reduced) {
            gsap.set(el, { opacity: 1, y: 0, x: 0, scale: 1, filter: "blur(0px)" });
            return;
        }

        const ctx = gsap.context(() => {
            const mm = gsap.matchMedia();
            mm.add("(prefers-reduced-motion: no-preference)", () => {
                gsap.fromTo(
                    el,
                    FROM_VARS[variant],
                    {
                        opacity: 1,
                        y: 0,
                        x: 0,
                        scale: 1,
                        filter: "blur(0px)",
                        duration: effectiveDuration,
                        ease:
                            variant === "scale-in" || variant === "blur-up"
                                ? "back.out(1.4)"
                                : "power2.out",
                        delay: delay / 1000,
                        scrollTrigger: {
                            trigger: el,
                            start,
                            once,
                            fastScrollEnd,
                            preventOverlaps,
                            toggleActions: "play none none none",
                        },
                        clearProps: "transform,opacity,filter",
                        overwrite: "auto",
                    },
                );
            });
            return () => mm.revert();
        }, el);

        return () => ctx.revert();
    }, [variant, delay, effectiveDuration, once, start, fastScrollEnd, preventOverlaps, reduced]);

    return ref;
}
