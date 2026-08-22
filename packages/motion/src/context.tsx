/**
 * Motion context — lightweight timing config for animation primitives.
 *
 * The motion package owns this context with sensible defaults. Apps wrap it
 * with their own provider (e.g. SoyMutDB's AnimationProvider) to feed
 * intensity-based values, device detection, and reduced-motion policy.
 *
 * Primitives call `useMotion()` to read duration/easing/reduced. If no
 * provider is mounted, defaults are used — making the package usable
 * standalone.
 */
import * as React from "react";

export interface MotionConfig {
    /** Effective duration in ms. */
    duration: number;
    durationFast: number;
    durationSlow: number;
    easing: string;
    stagger: number;
    /** True when motion should be avoided (off or reduced-motion). */
    reduced: boolean;
}

const DEFAULT_CONFIG: MotionConfig = {
    duration: 300,
    durationFast: 200,
    durationSlow: 500,
    easing: "cubic-bezier(0.16, 1, 0.3, 1)",
    stagger: 60,
    reduced: false,
};

const MotionContext = React.createContext<MotionConfig>(DEFAULT_CONFIG);

export interface MotionProviderProps {
    config: MotionConfig;
    children: React.ReactNode;
}

/** Provide motion timing config to all child primitives. */
export function MotionProvider({ config, children }: MotionProviderProps) {
    const value = React.useMemo(() => config, [config]);
    return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

/** Read the current motion config. Falls back to defaults if no provider. */
export function useMotion(): MotionConfig {
    return React.useContext(MotionContext);
}

export { DEFAULT_CONFIG };
