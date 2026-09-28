import { VueQueryPlugin } from "@tanstack/vue-query";
import { createApp } from "vue";
import { createPinia } from "pinia";

import { clearLegacyTokens, onAuthLogout, restoreSession } from "@soymutdb/api-client";

import App from "./App.vue";
import { markSessionEstablished } from "./lib/current-user";
import { applyDeploymentRelease, resolveInitialReleaseId } from "./lib/deployment";
import { installRouteMotion } from "./lib/motion";
import { createQueryClient } from "./lib/query-client";
import { registerServiceWorker } from "./lib/service-worker";
import { router } from "./router";
import "./style.css";

// Phase D Checkpoint B foundation wiring:
//   Pinia          -> client/deployment context (site variant, release, assembly)
//   Vue Router     -> portal routes + deep links (release/assembly/site params)
//   TanStack Query -> all server state (search/genes/variants via api-client)
//
// Pin the release BEFORE the app mounts: the api-client sends it as
// X-SoyMutDB-Release on every dynamic request, so a page rendered from release
// A must always query release A (DB-CORE-6 / review R1). The Pinia store reads
// the same value, so UI context and request context start in lockstep.
applyDeploymentRelease(resolveInitialReleaseId(import.meta.env.VITE_SOYMUTDB_RELEASE_ID));

// One-time migration: drop legacy persisted access/refresh tokens from
// localStorage/sessionStorage (sessions now live in memory + an HttpOnly
// refresh cookie). The admin console already runs this; the portal must too, or
// a browser that visited the React portal keeps a stale token readable by any
// same-origin script.
clearLegacyTokens();

// Try to restore a session from the HttpOnly refresh cookie. Failure is silent:
// the public portal degrades to the anonymous site.
//
// The result also gates the `GET /auth/me` probe (`lib/current-user.ts`). That
// probe travels over the auth-aware transport, which reports an unrefreshable
// 401 as a dead session — so asking it while anonymous would fire the logout
// handler below and bounce every public page to /login. Anonymous visitors must
// simply never ask.
void restoreSession().then(markSessionEstablished);

// Hard session death (a refresh failed mid-session): return to the sign-in
// page. The redirect lives here, in the app layer — the transport never
// hardcodes one. `router.resolve` keeps the deployment subpath correct instead
// of assuming the site is rooted at "/".
onAuthLogout(() => {
  if (typeof window === "undefined") return;
  const login = router.resolve({ name: "login" }).href;
  if (window.location.pathname === login || window.location.pathname.startsWith(`${login}/`)) {
    return;
  }
  window.location.assign(login);
});

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, { queryClient: createQueryClient() });
app.mount("#app");

// Announce the SPA handoff: the prerendered documents are inert until the first
// Vue commit, and a browser interaction that lands before then is silently
// discarded. `e2e/helpers.ts#waitForAppReady` waits on this attribute, so the
// boundary is explicit instead of a timing guess.
document.documentElement.dataset.appReady = "true";

// Motion runtime, wired after mount so it can never delay the first paint or
// the app-ready handoff above. It installs the `<html data-anim>` policy and
// wraps navigations in the native View Transitions API when the browser has it;
// reduced motion / unsupported browsers degrade to an instant swap. The router
// never awaits it, so a broken transition cannot block navigation (the boundary
// is the same "must not break" contract as AppErrorBoundary).
installRouteMotion(router);

// Register the offline service worker AFTER mount, and never await it: the
// build chain already emits dist/sw.js (precache manifest + cache version
// injected by scripts/gen-sw.js) but nothing registered it, so the whole
// offline / second-load caching policy was dead code.
//
// Production only — `vite dev` serves unbundled modules whose URLs HMR
// rewrites, so a cache-first worker there would return stale modules.
// Base-relative — `registerServiceWorker` joins sw.js onto
// `import.meta.env.BASE_URL`, so the gh-pages subpath (/soymutdb-next/) is
// registered at that prefix and the browser derives the matching scope from the
// script path, rather than a hardcoded "/sw.js" claiming the origin root.
// Failure is swallowed (console.warn only), so a broken worker cannot block the
// app-ready handoff above.
void registerServiceWorker();
