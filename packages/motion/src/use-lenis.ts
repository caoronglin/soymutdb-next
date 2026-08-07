/**
 * useLenis — Lenis smooth scroll hook with improved production settings.
 *
 * Integrates Lenis inertia scrolling with GSAP ScrollTrigger via the ticker.
 * Settings optimized for SoyMutDB:
 *   - lerp 0.08 (smooth but responsive; default 0.1)
 *   - normalizeWheel: true (consistent trackpad/mouse wheel)
 *   - smoothWheel: true
 *   - Mobile: native touch (disables Lenis) for battery/perf
 *   - Respects prefers-reduced-motion (no Lenis)
 *   - Syncs with GSAP ticker via lagSmoothing(0)
 *   - auto-respects data-lenis-prevent on interactive elements
 *
 * Usage (backward compatible):
 *   useLenis()              // enabled with defaults
 *   useLenis(false)         // disabled
 *   useLenis({ lerp: 0.1 }) // options object
 *
 * Returns the Lenis instance for imperative control (scrollTo, etc.).
 */
import * as React from "react";
import Lenis from "lenis";
import { gsap, ScrollTrigger } from "./gsap-setup";
import { useMotion } from "./context";

export interface UseLenisOptions {
    /** Enable/disable smooth scroll (default true). */
    enabled?: boolean;
    /** Lerp factor — lower = smoother/slower, higher = snappier (default 0.08). */
    lerp?: number;
    /** Duration of scroll animation in seconds (default 1.2). */
    duration?: number;
    /** Enable smooth wheel scrolling (default true). */
    smoothWheel?: boolean;
    /** Wheel multiplier — sensitivity (default 1). */
    wheelMultiplier?: number;
    /** Touch multiplier (default 1.5; note: on mobile Lenis is usually disabled). */
    touchMultiplier?: number;
    /** Root element to scroll (default window). */
    wrapper?: Window | HTMLElement;
}

export function useLenis(options: boolean | UseLenisOptions = {}): React.RefObject<Lenis | null> {
    // Backward compat: accept boolean as first arg
    const opts: UseLenisOptions = typeof options === "boolean" ? { enabled: options } : options;

    const {
        enabled = true,
        lerp = 0.08,
        duration,
        smoothWheel = true,
        wheelMultiplier = 1,
        touchMultiplier = 1.5,
        wrapper,
    } = opts;

    const lenisRef = React.useRef<Lenis | null>(null);
    const { reduced } = useMotion();

    React.useEffect(() => {
        if (!enabled) return;
        if (reduced) return;

        const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
        // On mobile, use native scroll for battery/perf
        if (isMobile && !wrapper) return;

        const lenis = new Lenis({
            duration: duration ?? (isMobile ? 0.8 : 1.2),
            lerp,
            smoothWheel,
            wheelMultiplier,
            touchMultiplier: isMobile ? 2 : touchMultiplier,
            orientation: "vertical",
            gestureOrientation: "vertical",
            wrapper: wrapper instanceof HTMLElement ? wrapper : undefined,
        });

        lenisRef.current = lenis;

        // Sync Lenis scroll updates with GSAP ScrollTrigger
        lenis.on("scroll", ScrollTrigger.update);

        // Integrate with GSAP ticker for RAF-synced updates
        const tickerCallback = (time: number) => {
            lenis.raf(time * 1000);
        };
        gsap.ticker.add(tickerCallback);
        gsap.ticker.lagSmoothing(0);

        // Add lenis class to html for CSS targeting
        if (typeof document !== "undefined") {
            document.documentElement.classList.add("lenis", "lenis-smooth");
        }

        // Refresh ScrollTrigger after setup
        requestAnimationFrame(() => ScrollTrigger.refresh());

        return () => {
            gsap.ticker.remove(tickerCallback);
            lenis.destroy();
            lenisRef.current = null;
            if (typeof document !== "undefined") {
                document.documentElement.classList.remove("lenis", "lenis-smooth");
            }
        };
    }, [enabled, lerp, duration, smoothWheel, wheelMultiplier, touchMultiplier, wrapper, reduced]);

    return lenisRef;
}

/**
 * Alias for semantic clarity — re-exported as useSmoothScroll.
 * Same API, different name for when you want to be explicit about
 * which scrolling behavior you're opting into.
 */
export const useSmoothScroll = useLenis;
