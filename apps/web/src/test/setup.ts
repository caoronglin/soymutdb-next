/**
 * Vitest global setup — one compatibility shim, no test behaviour of its own.
 *
 * ## Why this exists
 *
 * Node 25+ exposes an experimental `localStorage` global. Without
 * `--localstorage-file` it is a getter that returns `undefined`, but the
 * property still exists on `globalThis` (measured on Node 26.8.1):
 *
 *   $ node -e 'Object.getOwnPropertyDescriptor(globalThis, "localStorage")'
 *   { configurable: true, enumerable: false, get: [Function: get] }
 *   $ node -e 'typeof localStorage'
 *   undefined
 *   ExperimentalWarning: localStorage is not available because
 *   --localstorage-file was not provided.
 *
 * Vitest installs the jsdom environment's globals only for keys that are
 * *absent* from `globalThis`, so on Node 25+ jsdom's `localStorage` is never
 * installed and the global stays `undefined`. A test that touches it then fails
 * with
 *
 *   TypeError: Cannot read properties of undefined (reading 'clear')
 *
 * even though the same test passes on Node 24 (which has no such global). The
 * repository pins Node 24 (`.nvmrc`), so this is a *drift* shim: it keeps a
 * newer developer machine or CI image from producing a false failure.
 *
 * ## Why a fresh jsdom Storage rather than the environment's own
 *
 * The obvious fix — copy `window.localStorage` — does not work here, and the
 * measurement matters because the wrong version silently makes things worse.
 * Vitest's jsdom environment aliases the window to the global object itself:
 *
 *   typeof globalThis.window          // "object"
 *   globalThis.window === globalThis  // true
 *   globalThis.document.defaultView === globalThis // true
 *
 * So `window.localStorage` reads back the same shadowed `undefined`, and
 * writing it would replace Node's getter with a data property holding
 * `undefined`. There is no reachable jsdom Storage through the globals, so one
 * is created here instead. `jsdom` is already a devDependency of this package
 * (the SSG scripts use it), and the import is dynamic so tests running in the
 * `node` environment never pay for it.
 *
 * `sessionStorage` needs no shim: on Node 26 it is a working in-memory
 * `Storage` (only `localStorage` requires the file flag).
 *
 * Removal condition: drop this file once the pinned Node exposes a usable
 * `localStorage` without a flag, or once Vitest installs jsdom globals
 * unconditionally. Until then it must stay, because the alternative is a test
 * suite whose result depends on the Node version rather than on the code.
 */

const globalScope = globalThis as {
  document?: unknown;
  localStorage?: unknown;
};

const isDomEnvironment = typeof globalScope.document !== "undefined";
const localStorageMissing = typeof globalScope.localStorage === "undefined";

if (isDomEnvironment && localStorageMissing) {
  // jsdom refuses to expose Web Storage for an opaque origin, so the URL is
  // explicit. Only `localStorage` is taken from this throwaway window.
  const { JSDOM } = await import("jsdom");
  const { localStorage } = new JSDOM("", { url: "http://localhost/" }).window;

  Object.defineProperty(globalThis, "localStorage", {
    value: localStorage,
    configurable: true,
  });
}

/**
 * antd probes two browser APIs that jsdom does not implement:
 *
 * - `ResizeObserver`, used by `Table` (sticky header / scroll measurement) and
 *   other responsive components. A component that renders a table throws inside
 *   an effect without it, and the render is discarded.
 * - `matchMedia`, used for responsive breakpoints.
 *
 * Both shims are inert stand-ins: they exist so a component can mount in jsdom,
 * not to reproduce layout. Behaviour is asserted against the rendered DOM, so a
 * no-op observer is the correct level of fidelity here.
 */
if (isDomEnvironment) {
  const domScope = globalThis as {
    ResizeObserver?: unknown;
    matchMedia?: unknown;
  };

  if (typeof domScope.ResizeObserver === "undefined") {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.defineProperty(globalThis, "ResizeObserver", {
      value: ResizeObserverStub,
      configurable: true,
    });
  }

  if (typeof domScope.matchMedia !== "function") {
    // jsdom aliases `window` to the global object, so one definition covers both.
    const matchMedia = (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
    Object.defineProperty(globalThis, "matchMedia", {
      value: matchMedia,
      configurable: true,
    });
  }
}

export {};
