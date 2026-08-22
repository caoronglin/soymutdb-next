/**
 * @soymutdb/motion — Animation primitives for SoyMutDB.
 *
 * IntersectionObserver-based reveals and bounded CSS transitions. All primitives read timing config from
 * MotionProvider context (with sensible defaults if no provider is mounted).
 *
 * For app-specific intensity logic (localStorage, device detection), wrap
 * MotionProvider with your own provider that computes and passes MotionConfig.
 */

// Context
export { MotionProvider, useMotion, DEFAULT_CONFIG, type MotionConfig, type MotionProviderProps } from "./context";

// Hooks
export { useReveal, useViewportEntry, type UseRevealOptions } from "./use-reveal";

// Types
export { type RevealVariant, FROM_STYLES } from "./types";

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
