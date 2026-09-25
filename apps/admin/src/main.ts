import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createApp } from "vue";
import { createPinia } from "pinia";

import { setReleaseId } from "@soymutdb/api-client";

import App from "./App.vue";
import { router } from "./router";
import "./style.css";

// The console operates on one release at a time and every request it makes is
// pinned to it, so what the header shows and what the API serves cannot differ.
const releaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID?.trim();
setReleaseId(releaseId ? releaseId : null);

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin, { queryClient: new QueryClient() });
app.mount("#app");

document.documentElement.dataset.appReady = "true";
