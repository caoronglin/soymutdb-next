/**
 * View Transitions API helper — wraps document.startViewTransition with a
 * graceful fallback (immediate update) for unsupported browsers.
 *
 * Also detects Save-Data / prefers-reduced-motion and skips the transition
 * automatically to respect user preferences.
 */
import {
    parseMotionPreference,
    resolveMotionDecision,
    type MotionPreference,
    type MotionSessionCeiling,
} from "@soymutdb/ui-react";

let sessionCeiling: MotionSessionCeiling = "standard";

export function supportsViewTransitions(): boolean {
    return typeof document !== "undefined" && typeof document.startViewTransition === "function";
}

function shouldSkipTransition(): boolean {
    if (typeof window === "undefined") return true;
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
    const lowResource =
        (navigator.hardwareConcurrency ?? 4) <= 4 ||
        memory <= 2 ||
        /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
    if (conn?.saveData || lowResource) sessionCeiling = "minimal";

    let preference: MotionPreference = "auto";
    try {
        preference = parseMotionPreference(localStorage.getItem("soymutdb-animation-prefs"));
    } catch {
        // Storage can be unavailable in privacy modes; auto remains safe.
    }
    return resolveMotionDecision(
        preference,
        {
            reduced: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
            saveData: conn?.saveData === true,
            lowResource,
        },
        sessionCeiling,
    ).effective !== "standard";
}

/**
 * Trigger a view transition wrapping the given DOM update callback.
 *
 * In browsers that support View Transitions API, the browser will snapshot
 * the "before" state, run `updateDom`, then animate to the new state using
 * the ::view-transition pseudo-elements defined in CSS.
 *
 * In unsupported browsers, `updateDom` is called immediately with no animation.
 */
export function startViewTransition(updateDom: () => void | Promise<void>): ViewTransition | null {
    if (!supportsViewTransitions() || shouldSkipTransition()) {
        void Promise.resolve().then(updateDom);
        return null;
    }
    try {
        return document.startViewTransition!(updateDom);
    } catch {
        void Promise.resolve().then(updateDom);
        return null;
    }
}
