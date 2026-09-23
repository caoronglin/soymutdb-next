import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { applyDeploymentRelease, resolveInitialReleaseId } from "./lib/deployment";
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

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, { queryClient: new QueryClient() });
app.mount("#app");
