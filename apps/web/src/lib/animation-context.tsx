/**
 * Animation control center — global intensity, device-adaptive defaults,
 * localStorage persistence, and reduced-motion compliance.
 *
 * Wraps @soymutdb/motion's MotionProvider with SoyMutDB-specific policy
 * (intensity levels, localStorage key, device detection). The motion
 * package's primitives read timing config from MotionProvider.
 */
import * as React from "react";

export type AnimationIntensity = "off" | "minimal" | "normal" | "expressive";

export interface AnimationPrefs {
    intensity: AnimationIntensity;
    /** Whether the user has explicitly chosen (overrides device auto-downgrade). */
    explicit: boolean;
}

export interface AnimationContextValue {
    intensity: AnimationIntensity;
    /** Effective duration in ms for the current intensity. */
    duration: number;
    durationFast: number;
    durationSlow: number;
    easing: string;
    easingSpring: string;
    stagger: number;
    /** True when motion should be avoided (off or reduced-motion). */
    reduced: boolean;
    setIntensity: (next: AnimationIntensity) => void;
    /** Re-run device performance detection and apply a downgrade if needed. */
    recompute: () => void;
}

const STORAGE_KEY = "soymutdb-animation-prefs";

const DEFAULT_PREFS: AnimationPrefs = {
    intensity: "normal",
    explicit: false,
};

const INTENSITY_TOKENS: Record<
    Exclude<AnimationIntensity, "off">,
    { duration: number; durationFast: number; durationSlow: number; easing: string; easingSpring: string; stagger: number }
> = {
    minimal: {
        duration: 100,
        durationFast: 80,
        durationSlow: 150,
        easing: "ease-out",
        easingSpring: "ease-out",
        stagger: 20,
    },
    normal: {
        duration: 300,
        durationFast: 200,
        durationSlow: 500,
        easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        easingSpring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
        stagger: 60,
    },
    expressive: {
        duration: 500,
        durationFast: 300,
        durationSlow: 700,
        easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        easingSpring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
        stagger: 90,
    },
};

function readPrefs(): AnimationPrefs {
    if (typeof localStorage === "undefined") return DEFAULT_PREFS;
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return DEFAULT_PREFS;
        const parsed = JSON.parse(raw) as Partial<AnimationPrefs>;
        if (parsed.intensity && ["off", "minimal", "normal", "expressive"].includes(parsed.intensity)) {
            return { intensity: parsed.intensity, explicit: parsed.explicit ?? true };
        }
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

/** Detect low-power devices and suggest a downgrade. */
function detectDeviceTier(): "low" | "mid" | "high" {
    if (typeof navigator === "undefined") return "mid";
    const cores = navigator.hardwareConcurrency ?? 4;
    // deviceMemory is non-standard but widely available on Chromium.
    const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
    const isMobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
    if (cores <= 4 || memory <= 2 || isMobile) return "low";
    if (cores <= 8 || memory <= 4) return "mid";
    return "high";
}

function prefersReducedMotion(): boolean {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
    const [prefs, setPrefs] = React.useState<AnimationPrefs>(() => {
        const stored = readPrefs();
        // If the user hasn't explicitly chosen, downgrade on low-power devices.
        if (!stored.explicit) {
            const tier = detectDeviceTier();
            if (tier === "low") return { intensity: "minimal", explicit: false };
        }
        return stored;
    });

    const osReducedMotion = React.useMemo(() => prefersReducedMotion(), []);

    // Effective intensity: OS reduced-motion always wins.
    const effective: AnimationIntensity = osReducedMotion ? "off" : prefs.intensity;

    React.useEffect(() => {
        applyToDocument(effective);
    }, [effective]);

    // React to OS-level reduced-motion changes.
    React.useEffect(() => {
        if (typeof window === "undefined" || !window.matchMedia) return;
        const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
        const handler = () => applyToDocument(mq.matches ? "off" : prefs.intensity);
        mq.addEventListener?.("change", handler);
        return () => mq.removeEventListener?.("change", handler);
    }, [prefs.intensity]);

    const setIntensity = React.useCallback((next: AnimationIntensity) => {
        setPrefs({ intensity: next, explicit: true });
        writePrefs({ intensity: next, explicit: true });
    }, []);

    const recompute = React.useCallback(() => {
        setPrefs((prev) => {
            if (prev.explicit) return prev;
            const tier = detectDeviceTier();
            const next: AnimationIntensity = tier === "low" ? "minimal" : "normal";
            const updated = { intensity: next, explicit: false };
            writePrefs(updated);
            return updated;
        });
    }, []);

    const tokens =
        effective === "off"
            ? INTENSITY_TOKENS.minimal
            : INTENSITY_TOKENS[effective];

    const value: AnimationContextValue = React.useMemo(
        () => ({
            intensity: effective,
            duration: tokens.duration,
            durationFast: tokens.durationFast,
            durationSlow: tokens.durationSlow,
            easing: tokens.easing,
            easingSpring: tokens.easingSpring,
            stagger: tokens.stagger,
            reduced: effective === "off" || osReducedMotion,
            setIntensity,
            recompute,
        }),
        [effective, tokens, osReducedMotion, setIntensity, recompute],
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
