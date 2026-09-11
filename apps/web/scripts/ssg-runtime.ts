/**
 * Prepare the ownership handoff from build-time SSG markup to the React SPA.
 *
 * The generated HTML is not produced by the React route tree, so hydration is
 * intentionally forbidden. The fallback stays visible if the bundle or render
 * fails, and is removed only after React's first committed layout effect.
 */
export function prepareSsgHandoff(
    root: HTMLElement,
    ownerDocument: Pick<Document, "getElementById"> = document,
): () => void {
    // The pre-rendered markup is inert: its buttons and inputs belong to the
    // static document, not to React. Until the SPA commits, a user (or an
    // automated client) interacting with them gets a silent no-op. The handoff
    // therefore announces the *start* of the inert window here; the interactive
    // window is announced by the route tree once it actually commits (see
    // `AppReadySignal` in main.tsx). This is a readiness signal, not a security
    // or authorization boundary.
    const documentElement = (
        ownerDocument as unknown as Pick<Document, "documentElement">
    ).documentElement;
    documentElement.dataset.appReady = "false";

    const staticContent = ownerDocument.getElementById("ssg-content");
    if (!staticContent) {
        return () => {};
    }

    root.hidden = true;
    let completed = false;

    return () => {
        if (completed) return;
        completed = true;
        staticContent.remove();
        root.hidden = false;
    };
}
