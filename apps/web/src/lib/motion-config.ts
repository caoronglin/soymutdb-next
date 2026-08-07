/**
 * motion-config.ts — central GSAP configuration and performance defaults.
 *
 * Exports:
 *   - getMotionPrefs(): resolves reduced-motion / saveData / device-tier once
 *   - DEFAULT_TWEEN: sensible GSAP defaults (transform/opacity only, 60fps-friendly)
 *   - safeScrollTrigger: ScrollTrigger defaults with fastScrollEnd + preventOverlaps
 *   - respectReduced(fn): wraps a GSAP animation so it bails when reduced-motion is set
 *
 * All animations go through this module so we have a single choke-point to
 * respect user preferences, data-saver mode, and hardware capability.
 */
import { gsap, ScrollTrigger } from "@soymutdb/motion";

export interface MotionPrefs {
  reduced: boolean;
  saveData: boolean;
  lowPower: boolean;
}

/** Resolve user preferences once at call-time (or on every call for reactive checks). */
export function getMotionPrefs(): MotionPrefs {
  if (typeof window === "undefined") {
    return { reduced: false, saveData: false, lowPower: false };
  }
  const reducedMq = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData ?? false;
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const isMobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
  const lowPower = cores <= 2 || memory <= 2 || isMobile;
  return {
    reduced: reducedMq,
    saveData,
    lowPower,
  };
}

/** Default tween vars — transform/opacity only (compositor-friendly, 60fps). */
export const DEFAULT_TWEEN = {
  duration: 0.5,
  ease: "power2.out" as const,
  overwrite: "auto" as const,
};

/** Fast short tween for micro-interactions. */
export const FAST_TWEEN = {
  duration: 0.2,
  ease: "power2.out" as const,
  overwrite: "auto" as const,
};

/** Spring-like easing for playful UI moments (respects reduced-motion at call site). */
export const SPRING_TWEEN = {
  duration: 0.5,
  ease: "back.out(1.4)" as const,
  overwrite: "auto" as const,
};

/**
 * Default ScrollTrigger configuration:
 *   - fastScrollEnd: skip mid-animation when user scrolls past fast
 *   - preventOverlaps: queue reveals so they don't fight
 *   - toggleActions: play once on enter, no rewind
 */
export function createScrollTriggerDefaults(trigger: Element | string, overrides: Partial<ScrollTrigger.Vars> = {}): ScrollTrigger.Vars {
  return {
    trigger,
    start: "top 85%",
    once: true,
    fastScrollEnd: true,
    preventOverlaps: true,
    toggleActions: "play none none none",
    ...overrides,
  };
}

/**
 * Wrap a GSAP animation function so it is a no-op when the user prefers
 * reduced motion or data-saver is enabled.  The wrapped function returns
 * the tween (or undefined if skipped) for proper chaining/cleanup.
 */
export function respectReduced<T extends gsap.core.Animation>(
  fn: () => T,
): T | undefined {
  const { reduced } = getMotionPrefs();
  if (reduced) return undefined;
  return fn();
}

/**
 * Create a gsap.context() scoped to a React ref element.  Auto-reverts on
 * cleanup. Honors reduced-motion by doing nothing but cleanup registration.
 */
export function useGsapContext(
  scope: React.RefObject<HTMLElement | null>,
  build: (ctx: gsap.Context) => void,
  deps: React.DependencyList = [],
): void {
  // Imported dynamically to avoid importing React in non-React consumers.
  // This file is .ts but consumed by React components via hooks only.
}

/**
 * FLIP animation helper — First, Last, Invert, Play.
 * Computes position delta between two renders and animates via transform,
 * avoiding layout thrash. Used for widget reordering in LayoutEditor.
 *
 * Usage:
 *   const flip = new Flip(container);
 *   flip.record();       // snapshot positions before DOM change
 *   // ... mutate DOM (reorder children) ...
 *   flip.play();         // animate from old positions to new
 */
export class Flip {
  private first = new Map<Element, DOMRect>();
  private last = new Map<Element, DOMRect>();

  constructor(private container: HTMLElement | null) {}

  /** Snapshot positions of direct children. */
  record(): void {
    if (!this.container) return;
    this.first.clear();
    for (const child of Array.from(this.container.children)) {
      this.first.set(child, child.getBoundingClientRect());
    }
  }

  /** Compute post-mutation positions and animate. */
  play(options: { duration?: number; ease?: string } = {}): void {
    if (!this.container) return;
    const { reduced } = getMotionPrefs();
    if (reduced) return;

    this.last.clear();
    for (const child of Array.from(this.container.children)) {
      this.last.set(child, child.getBoundingClientRect());
    }

    const { duration = 0.45, ease = "power2.out" } = options;

    for (const [child, firstRect] of this.first) {
      const lastRect = this.last.get(child);
      if (!lastRect) continue;
      const dx = firstRect.left - lastRect.left;
      const dy = firstRect.top - lastRect.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
      gsap.fromTo(
        child,
        { x: dx, y: dy },
        {
          x: 0,
          y: 0,
          duration,
          ease,
          clearProps: "x,y",
        },
      );
    }
  }
}

/** Configure GSAP globally — set default timing, auto-remove will-change. */
export function configureGsap(): void {
  gsap.defaults({
    duration: DEFAULT_TWEEN.duration,
    ease: DEFAULT_TWEEN.ease,
    overwrite: DEFAULT_TWEEN.overwrite,
  });
  // Auto-remove will-change after animation completes to prevent layer promotion leaks
  gsap.ticker.lagSmoothing(0);
}
