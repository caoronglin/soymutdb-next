<script setup lang="ts">
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Shown for a route whose backing service is not part of this deployment.
 *
 * A core-only deployment runs the database without the optional genome browser
 * (or other optional services). The route stays reachable so a deep link gets a
 * clear explanation instead of a broken iframe or a 502 from an upstream that
 * was never started.
 */
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-2xl p-8" data-testid="feature-unavailable">
      <h1 class="text-2xl font-semibold">{{ t("common.featureUnavailableTitle") }}</h1>
      <p class="mt-3 text-sm opacity-70">{{ t("common.featureUnavailableBody") }}</p>
      <RouterLink to="/" class="mt-6 inline-block underline">
        {{ t("common.goHome") }}
      </RouterLink>
    </div>
  </ConfigProvider>
</template>
