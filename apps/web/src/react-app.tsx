import * as React from "react";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "./index.css";

import { routeTree } from "./routeTree.gen";
import { createQueryClient } from "./lib/query-client";
import { ThemeProvider } from "./lib/theme-provider";
import { AnimationProvider } from "./lib/animation-context";
import { initI18nOnce } from "./lib/i18n";
import { registry, SERVICES } from "./lib/di";
import { bus } from "./lib/event-bus";
import {
  clearLegacyTokens,
  onAuthLogout,
  restoreSession,
  setReleaseId,
} from "@soymutdb/api-client";
import { resolveAppUrl } from "./lib/deployment";
import { registerServiceWorker } from "./lib/service-worker";
import {
  parseMotionPreference,
  resolveMotionDecision,
  type MotionPreference,
} from "./lib/motion-policy";

const DesignSystemProvider = React.lazy(() =>
  import("./lib/design-system-provider").then(({ DesignSystemProvider }) => ({
    default: DesignSystemProvider,
  })),
);

clearLegacyTokens();
setReleaseId(import.meta.env.VITE_SOYMUTDB_RELEASE_ID);
void restoreSession();
initI18nOnce();

onAuthLogout(() => {
  if (typeof window === "undefined") return;
  const base = import.meta.env.BASE_URL;
  const loginPath = `${base}login`;
  if (window.location.pathname === loginPath || window.location.pathname.startsWith(`${loginPath}/`)) return;
  window.location.href = resolveAppUrl(base, "/login");
});

registry.register(SERVICES.EVENT_BUS, () => bus);
registry.register(SERVICES.I18N, initI18nOnce);

const queryClient = createQueryClient();
const router = createRouter({
  routeTree,
  basepath: import.meta.env.BASE_URL.replace(/\/$/, "") || "/",
  defaultPreload: "intent",
  defaultPreloadStaleTime: 30_000,
  scrollRestoration: true,
  context: { queryClient },
});

function shouldSkipViewTransition(): boolean {
  if (typeof window === "undefined") return true;
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  let preference: MotionPreference = "auto";
  try {
    preference = parseMotionPreference(localStorage.getItem("soymutdb-animation-prefs"));
  } catch {
    // Storage may be unavailable in privacy modes; auto remains safe.
  }
  return resolveMotionDecision(preference, {
    reduced: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
    saveData: connection?.saveData === true,
    lowResource:
      (navigator.hardwareConcurrency ?? 4) <= 4 ||
      memory <= 2 ||
      /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent),
  }).effective !== "standard";
}

if (typeof document !== "undefined" && typeof document.startViewTransition === "function") {
  const originalLoad = router.load.bind(router);
  router.load = (async (options: Parameters<typeof originalLoad>[0]) => {
    if (shouldSkipViewTransition()) return originalLoad(options);
    const transition = document.startViewTransition!(() => originalLoad(options));
    transition.ready.catch(() => {});
    return transition.finished;
  }) as typeof router.load;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

function AppReadySignal() {
  React.useLayoutEffect(() => {
    document.documentElement.dataset.appReady = "true";
  }, []);
  return null;
}

export default function ReactApp() {
  React.useEffect(() => {
    if (import.meta.env.PROD) {
      window.addEventListener("load", () => void registerServiceWorker(), { once: true });
    }

    if (import.meta.env.PROD) {
      void import("./lib/perf")
        .then(({ initPerfMonitoring }) => {
          initPerfMonitoring({
            endpoint: resolveAppUrl(import.meta.env.BASE_URL, "/track.gif"),
            sampleRate: 0.25,
          });
        })
        .catch(() => undefined);
    }
  }, []);

  return (
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AnimationProvider>
            <React.Suspense fallback={<RouterProvider router={router} />}>
              <DesignSystemProvider>
                <AppReadySignal />
                <RouterProvider router={router} />
              </DesignSystemProvider>
            </React.Suspense>
          </AnimationProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </React.StrictMode>
  );
}
