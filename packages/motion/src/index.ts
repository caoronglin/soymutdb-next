/**
 * @soymutdb/motion — Animation primitives for SoyMutDB.
 *
 * GSAP-powered scroll reveals, stagger, text effects, count-up, magnetic
 * button, and Lenis smooth scroll. All primitives read timing config from
 * MotionProvider context (with sensible defaults if no provider is mounted).
 *
 * Usage:
 *   import { MotionProvider, FadeUp, Stagger, useReveal, useSmoothScroll } from "@soymutdb/motion";
 *
 * For app-specific intensity logic (localStorage, device detection), wrap
 * MotionProvider with your own provider that computes and passes MotionConfig.
 */

// Context
export { MotionProvider, useMotion, DEFAULT_CONFIG, type MotionConfig, type MotionProviderProps } from "./context";

// GSAP setup (re-export so consumers share one registered instance)
export { gsap, ScrollTrigger } from "./gsap-setup";

// Hooks
export { useGsapReveal, type UseGsapRevealOptions } from "./use-gsap-reveal";
export { useLenis, useSmoothScroll, type UseLenisOptions } from "./use-lenis";
export { useReveal, useViewportEntry, type UseRevealOptions } from "./use-reveal";

// Types
export { type RevealVariant, FROM_VARS } from "./types";

// Components
export {
    FadeIn,
    type FadeInProps,
    FadeUp,
    type FadeUpProps,
    ScaleIn,
    type ScaleInProps,
    Reveal,
    type RevealProps,
    Stagger,
    type StaggerProps,
    TextReveal,
    type TextRevealProps,
    CountUp,
    type CountUpProps,
    MagneticButton,
    type MagneticButtonProps,
} from "./components";

// Utilities
export { cn } from "./utils";
