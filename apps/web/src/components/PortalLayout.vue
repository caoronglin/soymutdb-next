<script setup lang="ts">
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import PortalFooter from "./PortalFooter.vue";
import PortalHeader from "./PortalHeader.vue";

/**
 * Every portal page renders inside this frame: one ConfigProvider, one header
 * with the primary navigation and deployment context, and one footer. Views
 * only supply their own content, so the site variant / release / navigation
 * contract cannot drift page by page.
 */
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="flex min-h-screen flex-col bg-background text-foreground">
      <PortalHeader />
      <main id="main" class="flex-1">
        <slot />
      </main>
      <PortalFooter />
    </div>
  </ConfigProvider>
</template>
