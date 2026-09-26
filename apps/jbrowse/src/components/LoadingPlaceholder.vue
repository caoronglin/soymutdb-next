<template>
  <div
    class="flex h-full w-full flex-col items-center justify-center gap-4 bg-muted/20 p-8"
    role="status"
    aria-live="polite"
  >
    <svg
      class="size-8 animate-spin text-primary"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
    <div class="h-64 w-full max-w-3xl animate-pulse rounded-lg bg-muted" />
    <p class="text-sm text-muted-foreground">{{ t("browser.loading") }}</p>
  </div>
</template>

<script setup lang="ts">
import { t } from "../i18n";
</script>
