<template>
  <ConfigProvider :theme="themeConfig">
    <div class="flex min-h-screen flex-col bg-background text-foreground">
      <PortalHeader />
      <main id="main" class="flex-1">
        <!-- Route view area. The keyed reveal is what actually plays: this
             layout is re-instantiated for every route, so a `<Transition>`
             *inside* it never sees an update (its child is replaced together
             with the whole layout) — the new instance's reveal, armed on
             mount, is the entrance. When the native View Transition runtime
             exists it already cross-fades the root, so the reveal stands down.
             One wrapper only, so `#main` stays the single landmark and the
             page height is never animated. -->
        <RevealOnMount :key="route.fullPath" :disabled="viewTransitionsAvailable">
          <slot />
        </RevealOnMount>
      </main>
      <PortalFooter />
      <!-- The palette owns the ⌘K shortcut and renders nothing until opened. -->
      <PortalCommandPalette />
    </div>
  </ConfigProvider>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import PortalCommandPalette from "./PortalCommandPalette.vue";
import PortalFooter from "./PortalFooter.vue";
import PortalHeader from "./PortalHeader.vue";
import RevealOnMount from "./motion/RevealOnMount.vue";
import { supportsViewTransitions } from "../lib/motion";
import { usePortalTheme } from "../lib/theme";

/**
 * Every portal page renders inside this frame: one ConfigProvider, one header
 * with the primary navigation and deployment context, and one footer. Views
 * only supply their own content, so the site variant / release / navigation
 * contract cannot drift page by page.
 *
 * The provider follows the theme the header toggles: AntD carries its own token
 * set, so a dark portal with light AntD surfaces would be a mixed theme.
 */
const { theme } = usePortalTheme();
const themeConfig = computed(() => createThemeConfig({ dark: theme.value === "dark" }));

const route = useRoute();
// Read once: the runtime feature cannot appear mid-session.
const viewTransitionsAvailable = supportsViewTransitions();
</script>
