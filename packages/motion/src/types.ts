/** Shared types for motion primitives. */

export type RevealVariant =
    | "fade-up"
    | "fade-in"
    | "fade-down"
    | "scale-in"
    | "slide-in-right"
    | "slide-in-left"
    | "blur-up";

/** Hidden (pre-reveal) GSAP vars per variant. */
export const FROM_VARS: Record<RevealVariant, {
    opacity?: number;
    y?: number;
    x?: number;
    scale?: number;
    filter?: string;
}> = {
    "fade-up": { opacity: 0, y: 24 },
    "fade-in": { opacity: 0 },
    "fade-down": { opacity: 0, y: -16 },
    "scale-in": { opacity: 0, scale: 0.94 },
    "slide-in-right": { opacity: 0, x: 32 },
    "slide-in-left": { opacity: 0, x: -32 },
    "blur-up": { opacity: 0, y: 20, scale: 0.98, filter: "blur(12px)" },
};