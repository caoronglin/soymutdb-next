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
import * as React from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import i18n from "@soymutdb/i18n";

// Fonts — HarmonyOS Sans SC (local, covers Latin + CJK), JetBrains Mono (code).
// Fraunces/Inter replaced by HarmonyOS Sans SC (2026-08 redesign).
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";

import "./index.css";

import { routeTree } from "./routeTree.gen";
import { createQueryClient } from "./lib/query-client";
import { ThemeProvider } from "./lib/theme-provider";
import { AnimationProvider } from "./lib/animation-context";
import { ToastProvider } from "@soymutdb/ui";
import { createAntdTheme, loadAntdLocale } from "./lib/antd-theme";
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

// ---------------------------------------------------------------------------
// AntD ConfigProvider wrapper — children form, does not touch the router tree.
// theme: createAntdTheme()（OKLCH 覆盖 + reduced-motion，见 lib/antd-theme.ts）
// locale: i18next `languageChanged` 事件驱动（oracle 遗漏 #1），按需 import
// dayjs/antd locale 包（约 8KB）。路由级懒加载占位见 loadAntdLocale 注释。
// ---------------------------------------------------------------------------
function AntdProvider({ children }: { children: React.ReactNode }) {
    const [locale, setLocale] = React.useState<Locale | null>(null);

    React.useEffect(() => {
        let disposed = false;
        const apply = (lng?: string) => {
            void loadAntdLocale(lng ?? i18n.language).then((l) => {
                if (!disposed) setLocale(l);
            });
        };
        apply();
        const onChange = (lng: string) => apply(lng);
        i18n.on("languageChanged", onChange);
        return () => {
            disposed = true;
            i18n.off("languageChanged", onChange);
        };
    }, []);

    const theme = React.useMemo(() => createAntdTheme(), []);

    return (
        <ConfigProvider locale={locale ?? undefined} theme={theme}>
            {children}
        </ConfigProvider>
    );
}

createRoot(rootEl).render(
    <React.StrictMode>
        <AntdProvider>
            <QueryClientProvider client={queryClient}>
                <ThemeProvider>
                    <AnimationProvider>
                        <ToastProvider>
                            <RouterProvider router={router} />
                            {null /* devtools hidden */}
                        </ToastProvider>
                    </AnimationProvider>
                </ThemeProvider>
            </QueryClientProvider>
        </AntdProvider>
    </React.StrictMode>,
);

// ---------------------------------------------------------------------------
// Service Worker 注册 — 静态资源缓存（D3，追加段：不改动上方现有逻辑）
//
// 仅生产构建（import.meta.env.PROD）+ 开关（VITE_SW_ENABLED !== "false"）时注册；
// 延迟到 window load 之后，避免与首屏渲染竞争。
// gh-pages 子路径部署（/soymutdb-next/）下 vite 未配置 base（BASE_URL === "/"），
// 此时用相对路径 "sw.js" 注册，以当前文档路径解析到实际部署前缀 —— 两种部署都正确。
// 注册/更新失败一律静默：SW 是渐进增强，绝不阻断应用。
// SW 策略与构建注入见 docs/design/service-worker.md 与 scripts/gen-sw.js。
// ---------------------------------------------------------------------------
if (import.meta.env.PROD && import.meta.env.VITE_SW_ENABLED !== "false") {
    window.addEventListener("load", () => {
        if (!("serviceWorker" in navigator)) return;
        const base = import.meta.env.BASE_URL;
        const swUrl = base && base !== "/" ? `${base}sw.js` : "sw.js";
        navigator.serviceWorker.register(swUrl).catch(() => {
            /* 静默 —— SW 不可用时应用照常运行 */
        });
    });
}
