/** Shared types for motion primitives. */

import type React from "react";

export type RevealVariant =
    | "fade-up"
    | "fade-in"
    | "fade-down"
    | "scale-in"
    | "slide-in-right"
    | "slide-in-left"
    | "blur-up";

/** Compositor-only initial styles for viewport reveals. */
export const FROM_STYLES: Record<RevealVariant, React.CSSProperties> = {
    "fade-up": { opacity: 0, transform: "translateY(16px)" },
    "fade-in": { opacity: 0 },
    "fade-down": { opacity: 0, transform: "translateY(-12px)" },
    "scale-in": { opacity: 0, transform: "scale(0.98)" },
    "slide-in-right": { opacity: 0, transform: "translateX(16px)" },
    "slide-in-left": { opacity: 0, transform: "translateX(-16px)" },
    "blur-up": { opacity: 0, transform: "translateY(12px)" },
};
