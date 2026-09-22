import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router";

// Phase D Checkpoint B foundation wiring:
//   Pinia          -> client/deployment context (site variant, release, assembly)
//   Vue Router     -> portal routes + deep links (release/assembly/site params)
//   TanStack Query -> all server state (search/genes/variants via api-client)
const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, { queryClient: new QueryClient() });
app.mount("#app");
