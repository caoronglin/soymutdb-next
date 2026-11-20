/**
 * Animation control center — global intensity, device-adaptive defaults,
 * localStorage persistence, and reduced-motion compliance.
 *
 * Owns the portal policy for intensity, persistence and device detection.
 */
import * as React from "react";
import {
    parseMotionPreference,
    resolveMotionDecision,
    type EffectiveMotionMode,
    type MotionPreference,
    type MotionSessionCeiling,
    type MotionSignals,
} from "@soymutdb/ui-react";

export type AnimationIntensity = MotionPreference;
export interface AnimationPrefs {
    intensity: AnimationIntensity;
}

export interface AnimationContextValue {
    /** Saved user choice. */
    preference: MotionPreference;
    /** Resolved mode after accessibility and session resource limits. */
    intensity: EffectiveMotionMode;
    decisionReason: ReturnType<typeof resolveMotionDecision>["reason"];
    /** Effective duration in ms for the current intensity. */
    duration: number;
    durationFast: number;
    durationSlow: number;
    easing: string;
    stagger: number;
    /** True when motion should be avoided (off or reduced-motion). */
    reduced: boolean;
    setIntensity: (next: AnimationIntensity) => void;
    /** Re-run device performance detection and apply a downgrade if needed. */
    recompute: () => void;
}

const STORAGE_KEY = "soymutdb-animation-prefs";

const DEFAULT_PREFS: AnimationPrefs = {
    intensity: "auto",
};

const INTENSITY_TOKENS: Record<
    Exclude<EffectiveMotionMode, "off">,
    { duration: number; durationFast: number; durationSlow: number; easing: string; stagger: number }
> = {
    minimal: {
        duration: 100,
        durationFast: 80,
        durationSlow: 150,
        easing: "ease-out",
        stagger: 20,
    },
    standard: {
        duration: 300,
        durationFast: 200,
        durationSlow: 500,
        easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        stagger: 60,
    },
};
function readPrefs(): AnimationPrefs {
    if (typeof localStorage === "undefined") return DEFAULT_PREFS;
    try {
        return { intensity: parseMotionPreference(localStorage.getItem(STORAGE_KEY)) };
    } catch {
        /* ignore malformed storage */
    }
    return DEFAULT_PREFS;
}

function writePrefs(prefs: AnimationPrefs): void {
    if (typeof localStorage === "undefined") return;
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
        /* storage may be unavailable in private mode */
    }
}

function readMotionSignals(reducedQuery?: MediaQueryList): MotionSignals {
    if (typeof navigator === "undefined") return {};
    const cores = navigator.hardwareConcurrency ?? 4;
    const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
    const isMobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    return {
        reduced:
            reducedQuery?.matches ??
            (typeof window !== "undefined" &&
                window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true),
        saveData: connection?.saveData === true,
        lowResource: cores <= 4 || memory <= 2 || isMobile,
    };
}

function applyToDocument(intensity: AnimationIntensity): void {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    root.setAttribute("data-anim", intensity);
}

const AnimationContext = React.createContext<AnimationContextValue | null>(null);

export interface AnimationProviderProps {
    children: React.ReactNode;
}

export function AnimationProvider({ children }: AnimationProviderProps) {
    const [prefs, setPrefs] = React.useState<AnimationPrefs>(readPrefs);
    const [environment, setEnvironment] = React.useState<{
        signals: MotionSignals;
        ceiling: MotionSessionCeiling;
    }>(() => {
        const signals = readMotionSignals();
        return {
            signals,
            ceiling: signals.saveData || signals.lowResource ? "minimal" : "standard",
        };
    });

    const decision = resolveMotionDecision(
        prefs.intensity,
        environment.signals,
        environment.ceiling,
    );
    const effective = decision.effective;

    React.useEffect(() => {
        applyToDocument(effective);
    }, [effective]);

    // One subscription owns all environment changes. The ceiling can only
    // move down during a session, even if Save-Data is later switched off.
    React.useEffect(() => {
        if (typeof window === "undefined" || !window.matchMedia) return;
        const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
        const connection = (navigator as Navigator & {
            connection?: EventTarget & { saveData?: boolean };
        }).connection;
        const handler = () => {
            const signals = readMotionSignals(mq);
            setEnvironment((previous) => ({
                signals,
                ceiling:
                    previous.ceiling === "minimal" || signals.saveData || signals.lowResource
                        ? "minimal"
                        : "standard",
            }));
        };
        mq.addEventListener?.("change", handler);
        connection?.addEventListener?.("change", handler);
        return () => {
            mq.removeEventListener?.("change", handler);
            connection?.removeEventListener?.("change", handler);
        };
    }, []);
    const setIntensity = React.useCallback((next: AnimationIntensity) => {
        const updated = { intensity: next };
        setPrefs(updated);
        writePrefs(updated);
    }, []);

    const recompute = React.useCallback(() => {
        const signals = readMotionSignals();
        setEnvironment((previous) => ({
            signals,
            ceiling:
                previous.ceiling === "minimal" || signals.saveData || signals.lowResource
                    ? "minimal"
                    : "standard",
        }));
    }, []);

    const tokens =
        effective === "off"
            ? INTENSITY_TOKENS.minimal
            : INTENSITY_TOKENS[effective];

    const value: AnimationContextValue = React.useMemo(
        () => ({
            preference: prefs.intensity,
            intensity: effective,
            decisionReason: decision.reason,
            duration: tokens.duration,
            durationFast: tokens.durationFast,
            durationSlow: tokens.durationSlow,
            easing: tokens.easing,
            stagger: tokens.stagger,
            reduced: effective === "off",
            setIntensity,
            recompute,
        }),
        [prefs.intensity, effective, decision.reason, tokens, setIntensity, recompute],
    );

    return (
        <AnimationContext.Provider value={value}>
            {children}
        </AnimationContext.Provider>
    );
}

export function useAnimation(): AnimationContextValue {
    const ctx = React.useContext(AnimationContext);
    if (!ctx) {
        throw new Error("useAnimation must be used within an AnimationProvider");
    }
    return ctx;
}

/**
 * Context read for leaf components that may render in isolation (unit tests,
 * standalone widgets). Callers must supply sensible defaults when it is null.
 */
export function useAnimationOptional(): AnimationContextValue | null {
    return React.useContext(AnimationContext);
}
