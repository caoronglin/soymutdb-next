/**
 * App entry — wires React 19, TanStack Router + Query, theme, animation, i18n.
 *
 * Routes are code-split via TanStack Router's autoCodeSplitting (see vite.config).
 *
 * Also boots the decoupled architecture pieces:
 *   - Event bus (imported for side effects + global singleton)
 *   - DI service registry (api client, analytics, i18n, theme)
 *   - <soymutdb-widget> Custom Element (Shadow DOM + IntersectionObserver lazy load)
 *   - View Transitions API for route navigations (graceful fallback)
 *   - Lazy Web Worker for off-thread search/filter computations
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { TanStackRouterDevtools } from "@tanstack/router-devtools";

// Fonts (Fontsource) — imported as JS modules so Vite resolves each CSS
// file's internal url(./files/...) relative to the package itself.
// (Tailwind v4 postcss inlining breaks those relative paths; see index.css.)
import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/fraunces/latin-600.css";
import "@fontsource/fraunces/latin-700.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";

import "./index.css";

import { routeTree } from "./routeTree.gen";
import { createQueryClient } from "./lib/query-client";
import { ThemeProvider } from "./lib/theme-provider";
import { AnimationProvider } from "./lib/animation-context";
import { initI18nOnce } from "./lib/i18n";
import { initWidgetLoader } from "./lib/widget-loader";
import { registry, SERVICES } from "./lib/di";
import { bus } from "./lib/event-bus";
import { clearLegacyTokens, restoreSession, onAuthLogout } from "@soymutdb/api-client";

// One-time migration: drop legacy persisted access/refresh tokens from
// localStorage/sessionStorage (sessions now live in memory + HttpOnly cookie).
clearLegacyTokens();

// Try to restore a session from the HttpOnly refresh cookie. Failure is
// silent — the public site degrades to anonymous state.
void restoreSession();

// Hard session death (refresh failed mid-session): return to the login page.
// The redirect lives here (app layer) — the transport never hardcodes it.
onAuthLogout(() => {
    if (typeof window === "undefined") return;
    const { pathname } = window.location;
    if (pathname.startsWith("/login")) return;
    window.location.href = "/login";
});

// Register the <soymutdb-widget> custom element (side-effect import).
// This is a standalone Custom Element — no React dependency.
import "./components/soymutdb-widget";

// Initialise i18n before rendering so the first paint has translations.
initI18nOnce();

// Boot the widget loader (scans [data-widget] placeholders, sets up
// Trusted Types policy, hydrates any server-inlined dynamic widgets).
initWidgetLoader();

// ---------------------------------------------------------------------------
// DI service registration — services are lazily instantiated on first get()
// ---------------------------------------------------------------------------
registry.register(SERVICES.EVENT_BUS, () => bus);
registry.register(SERVICES.I18N, () => initI18nOnce);
// Theme + API clients are registered after providers mount (see below).

const queryClient = createQueryClient();

const router = createRouter({
    routeTree,
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    context: { queryClient },
});

// ---------------------------------------------------------------------------
// View Transitions API — wrap router.load() so route changes crossfade.
// Browsers without startViewTransition fall through to normal navigation.
// ---------------------------------------------------------------------------
function vtSupported(): boolean {
    return typeof document !== "undefined" && typeof document.startViewTransition === "function";
}
function skipVT(): boolean {
    if (typeof window === "undefined") return true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return true;
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (conn?.saveData) return true;
    return false;
}
if (vtSupported()) {
    const originalLoad = router.load.bind(router);
    router.load = (async (opts: Parameters<typeof originalLoad>[0]) => {
        if (skipVT()) return originalLoad(opts);
        // startViewTransition snapshots current DOM, runs the callback (which
        // triggers React re-render), then animates to the new state.
        const vt = document.startViewTransition!(() => originalLoad(opts));
        // Swallow "transition skipped" errors (e.g. overlapping navigations).
        vt.ready.catch(() => {});
        return vt.finished;
    }) as typeof router.load;
}

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root element not found");

// ---------------------------------------------------------------------------
// Lazy-initialize the search Web Worker during idle time so it doesn't
// compete for the main thread on first paint.
// ---------------------------------------------------------------------------
function lazyInitWorker(): void {
    const ric = (window as unknown as {
        requestIdleCallback?: (cb: () => void) => void;
    }).requestIdleCallback;
    const schedule = ric ?? ((cb: () => void) => setTimeout(cb, 500));
    schedule(() => {
        // Dynamic import triggers worker download + instantiation only after
        // the app is idle. The client also has a main-thread fallback.
        import("./lib/search-worker-client").catch(() => {
            /* worker is optional — search falls back to main thread */
        });
    });
}
lazyInitWorker();

createRoot(rootEl).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <ThemeProvider>
                <AnimationProvider>
                    <RouterProvider router={router} />
                    {import.meta.env.DEV ? <TanStackRouterDevtools router={router} position="bottom-right" /> : null}
                </AnimationProvider>
            </ThemeProvider>
        </QueryClientProvider>
    </StrictMode>,
);
