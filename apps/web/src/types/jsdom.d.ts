/**
 * Minimal ambient declaration for the `jsdom` module.
 *
 * The repository consumes jsdom from two places and neither needs its full API
 * surface:
 *
 *   - `apps/web/scripts/ssg-content.ts` builds a throwaway `JSDOM` window so
 *     DOMPurify has a DOM to sanitise with;
 *   - `apps/web/src/test/setup.ts` builds one to obtain a real `Storage`
 *     implementation (Node 25+ shadows `globalThis.localStorage`; see that
 *     file's header).
 *
 * jsdom ships no TypeScript types and `@types/jsdom` is not a dependency, so
 * only the members actually used are declared. This is deliberately narrow: a
 * broad `any` would let a typo in a call site compile, while a hand-written
 * full API would silently drift from the installed version.
 *
 * If a future change needs more of the jsdom API, prefer adding the real
 * `@types/jsdom` package over growing this file.
 */
declare module "jsdom" {
  export interface JSDOMOptions {
    /** Required for Web Storage: an opaque origin exposes none. */
    url?: string;
  }

  export interface JSDOMWindow {
    readonly localStorage: Storage;
    readonly sessionStorage: Storage;
    document: Document;
  }

  export class JSDOM {
    constructor(html?: string, options?: JSDOMOptions);
    readonly window: JSDOMWindow;
  }
}
