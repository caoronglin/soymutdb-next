import { VueQueryPlugin } from "@tanstack/vue-query";
import { createApp } from "vue";
import { createPinia } from "pinia";

import { clearLegacyTokens, setReleaseId } from "@soymutdb/api-client";

import App from "./App.vue";
import { router } from "./router";
import { createQueryClient } from "./lib/query-client";
import "./style.css";

// The console operates on one release at a time and every request it makes is
// pinned to it, so what the header shows and what the API serves cannot differ.
const releaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID?.trim();
setReleaseId(releaseId ? releaseId : null);

// Sessions live in memory + an HttpOnly cookie now; drop any access/refresh token
// an earlier console persisted (the React boot did the same one-time sweep).
clearLegacyTokens();

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, { queryClient: createQueryClient() });
app.mount("#app");

document.documentElement.dataset.appReady = "true";
