<script setup lang="ts">
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="py-10">
      <h1 class="text-xl font-semibold">{{ t("common.notFound") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("common.notFoundDescription") }}</p>
      <RouterLink to="/" class="mt-4 inline-block underline">{{ t("common.goHome") }}</RouterLink>
    </div>
  </ConfigProvider>
</template>
