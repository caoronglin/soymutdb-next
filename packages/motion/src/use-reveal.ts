/**
 * useReveal — IntersectionObserver viewport reveal hook.
 *
 * Uses the browser's IntersectionObserver without scroll listeners. The reveal is a
 * bounded opacity/transform CSS transition and never uses blur or springs.
 *
 * Honors:
 *   - prefers-reduced-motion (immediate final state)
 *   - once: true by default (play once, no re-trigger on scroll back)
 *   - threshold + rootMargin for fine-grained visibility control
 */
import * as React from "react";
import { useMotion } from "./context";
import { FROM_STYLES, type RevealVariant } from "./types";

export interface UseRevealOptions {
    /** Animation variant (default: 'fade-up'). */
    variant?: RevealVariant;
    /** Delay in ms before animation starts (default: 0). */
    delay?: number;
    /** Duration in seconds. */
    duration?: number;
    /** CSS easing function. */
    ease?: string;
    /** Intersection threshold 0..1 — how much visible to trigger (default: 0.15). */
    threshold?: number;
    /** Root margin for IntersectionObserver (default: '0px 0px -10% 0px'). */
    rootMargin?: string;
    /** Only play once (default: true). */
    once?: boolean;
    /** Stagger delay (in seconds) for child elements. */
    stagger?: number;
    /** CSS selector for children to stagger (default: ':scope > *'). */
    childSelector?: string;
    /** Callback when animation completes. */
    onComplete?: () => void;
}

export function useReveal<T extends HTMLElement = HTMLDivElement>(
    options: UseRevealOptions = {},
): React.RefObject<T | null> {
    const {
        variant = "fade-up",
        delay = 0,
        duration: dur,
        ease,
        threshold = 0.15,
        rootMargin = "0px 0px -10% 0px",
        once = true,
        stagger,
        childSelector = ":scope > *",
        onComplete,
    } = options;

    const ref = React.useRef<T | null>(null);
    const { reduced, duration: contextDuration, easing } = useMotion();
    const hasPlayedRef = React.useRef(false);

    const effectiveEase = ease ?? easing;
    const effectiveDuration = dur ?? contextDuration / 1000;

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;

        // Determine target elements
        const targets = stagger !== undefined
            ? Array.from(el.querySelectorAll<HTMLElement>(childSelector))
            : [el];

        if (targets.length === 0) return;

        const show = () => {
            targets.forEach((target, index) => {
                target.style.opacity = "1";
                target.style.transform = "none";
                target.style.transitionProperty = "opacity, transform";
                target.style.transitionDuration = `${Math.min(180, effectiveDuration * 1000)}ms`;
                target.style.transitionTimingFunction = effectiveEase;
                target.style.transitionDelay = `${delay + index * (stagger ?? 0) * 1000}ms`;
            });
        };

        if (reduced) {
            show();
            onComplete?.();
            return;
        }

        const initial = FROM_STYLES[variant] ?? FROM_STYLES["fade-up"];
        targets.forEach((target) => Object.assign(target.style, initial));

        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue;

                    if (once && hasPlayedRef.current) {
                        observer.disconnect();
                        return;
                    }

                    requestAnimationFrame(() => {
                        show();
                        window.setTimeout(
                            () => onComplete?.(),
                            delay + effectiveDuration * 1000,
                        );
                    });

                    hasPlayedRef.current = true;

                    if (once) {
                        observer.disconnect();
                    }
                }
            },
            { threshold, rootMargin },
        );

        observer.observe(el);

        return () => {
            observer.disconnect();
        };
    }, [variant, delay, effectiveDuration, effectiveEase, threshold, rootMargin, once, stagger, childSelector, reduced, onComplete]);

    return ref;
}

/**
 * useViewportEntry — lightweight hook that just tracks whether an element is
 * in the viewport. No animations, just a boolean. Useful for lazy-loading
 * heavy content (like the canvas track viewer) only when visible.
 */
export function useViewportEntry<T extends HTMLElement = HTMLDivElement>(
    options: { threshold?: number; rootMargin?: string } = {},
): { ref: React.RefObject<T | null>; inView: boolean } {
    const { threshold = 0.05, rootMargin = "200px" } = options;
    const ref = React.useRef<T | null>(null);
    const [inView, setInView] = React.useState(false);

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const obs = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    setInView(entry.isIntersecting);
                }
            },
            { threshold, rootMargin },
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, [threshold, rootMargin]);

    return { ref, inView };
}
