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
    const staticContent = ownerDocument.getElementById("ssg-content");
    if (!staticContent) return () => {};

    root.hidden = true;
    let completed = false;

    return () => {
        if (completed) return;
        completed = true;
        staticContent.remove();
        root.hidden = false;
    };
}
