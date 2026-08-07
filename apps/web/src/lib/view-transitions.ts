/**
 * View Transitions API helper — wraps document.startViewTransition with a
 * graceful fallback (immediate update) for unsupported browsers.
 *
 * Also detects Save-Data / prefers-reduced-motion and skips the transition
 * automatically to respect user preferences.
 */

export function supportsViewTransitions(): boolean {
    return typeof document !== "undefined" && typeof document.startViewTransition === "function";
}

function shouldSkipTransition(): boolean {
    if (typeof window === "undefined") return true;
    // OS-level reduced motion
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return true;
    // Save-Data header via Network Information API
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (conn?.saveData) return true;
    return false;
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
