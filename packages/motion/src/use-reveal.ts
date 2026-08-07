/**
 * useReveal — IntersectionObserver + GSAP viewport reveal hook.
 *
 * A simpler, lower-overhead alternative to useGsapReveal that uses the
 * browser's IntersectionObserver (no ScrollTrigger plugin needed, no scroll
 * listener). When the element enters the viewport, a GSAP tween plays from
 * a hidden state to the element's natural state.
 *
 * Why useReveal vs useGsapReveal:
 *   - useReveal uses IntersectionObserver (cheaper, no scroll event overhead)
 *   - useGsapReveal uses ScrollTrigger (more features: pin, scrub, callbacks)
 *   - For simple "fade in when visible" cases, useReveal is preferred.
 *
 * Honors:
 *   - prefers-reduced-motion (immediate final state)
 *   - once: true by default (play once, no re-trigger on scroll back)
 *   - threshold + rootMargin for fine-grained visibility control
 *   - gsap.context() for proper cleanup on unmount
 */
import * as React from "react";
import { gsap } from "./gsap-setup";
import { useMotion } from "./context";
import { FROM_VARS, type RevealVariant } from "./types";

export interface UseRevealOptions {
    /** Animation variant (default: 'fade-up'). */
    variant?: RevealVariant;
    /** Delay in ms before animation starts (default: 0). */
    delay?: number;
    /** Duration in seconds (default: 0.6). */
    duration?: number;
    /** Easing function (default: 'power2.out', or 'back.out(1.4)' for scale-in). */
    ease?: string;
    /** Intersection threshold 0..1 — how much visible to trigger (default: 0.15). */
    threshold?: number;
    /** Root margin for IntersectionObserver (default: '0px 0px -10% 0px'). */
    rootMargin?: string;
    /** Only play once (default: true). */
    once?: boolean;
    /** Stagger delay (in seconds) for child elements — if set, animates children of the ref. */
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

    // Default easing based on variant if not explicitly provided
    const effectiveEase = ease ?? (variant === "scale-in" || variant === "blur-up" ? "back.out(1.4)" : "power2.out");
    const effectiveDuration = dur ?? Math.max(0.2, contextDuration / 1000);

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;

        // Determine target elements
        const targets = stagger !== undefined
            ? Array.from(el.querySelectorAll<HTMLElement>(childSelector))
            : [el];

        if (targets.length === 0) return;

        // Reduced motion: immediately show, no animation
        if (reduced) {
            gsap.set(targets, { opacity: 1, y: 0, x: 0, scale: 1, filter: "blur(0px)", clearProps: "transform,opacity,filter" });
            onComplete?.();
            return;
        }

        // Set initial hidden state
        const fromVars = FROM_VARS[variant] ?? FROM_VARS["fade-up"];
        gsap.set(targets, fromVars);

        let ctx: gsap.Context | null = null;
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue;

                    if (once && hasPlayedRef.current) {
                        observer.disconnect();
                        return;
                    }

                    ctx = gsap.context(() => {
                        gsap.to(targets, {
                            opacity: 1,
                            y: 0,
                            x: 0,
                            scale: 1,
                            filter: "blur(0px)",
                            duration: effectiveDuration,
                            ease: effectiveEase,
                            delay: delay / 1000,
                            stagger: stagger ?? 0,
                            clearProps: "transform,opacity,filter",
                            onComplete,
                            overwrite: "auto",
                        });
                    }, el);

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
            ctx?.revert();
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
