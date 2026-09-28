<script setup lang="ts">
// Router host with runtime branding. The site variant is the build-time
// constant (DB-CORE-5); routing and per-page state live under src/router +
// src/stores. Branding is applied to the document chrome here so every route
// gets the same wordmark, title and favicon; the static HTML keeps the
// build-time defaults until (and if) the snapshot arrives.
import { watchEffect } from "vue";

import AppErrorBoundary from "./components/AppErrorBoundary.vue";
import { DEFAULT_FAVICON_HREF, useSiteBranding } from "./lib/branding";

const { displayName, iconUrl } = useSiteBranding();

watchEffect(() => {
  if (typeof document === "undefined") return;
  document.title = displayName.value;

  const favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!favicon) return;
  if (iconUrl.value) {
    favicon.href = iconUrl.value;
    // A verified upload is PNG/JPEG/WebP; the stale svg+xml type would mislead
    // browsers that honor the attribute over content sniffing.
    favicon.removeAttribute("type");
  } else {
    favicon.href = DEFAULT_FAVICON_HREF;
    favicon.type = "image/svg+xml";
  }
});
</script>

<template>
  <!-- One boundary for every route: a thrown render error shows the fallback
       with a retry instead of unmounting the app into a blank page. -->
  <AppErrorBoundary v-slot="{ attempt }">
    <RouterView :key="attempt" />
  </AppErrorBoundary>
</template>
