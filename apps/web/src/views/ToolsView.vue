<script setup lang="ts">
import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-4xl px-4 py-8">
      <RouterLink to="/" class="text-sm underline opacity-70">{{ t("nav.home") }}</RouterLink>
      <h1 class="mt-2 text-2xl font-semibold">{{ t("tools.title") }}</h1>
      <p class="mt-2 max-w-2xl text-sm opacity-70">
        {{ t("tools.cardSubtitle") }}
      </p>

      <RouterLink
        to="/tools/seqfetch"
        class="mt-6 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="seqfetch-tool-link"
      >
        <h2 class="font-medium">{{ t("tools.seqfetch.title") }}</h2>
        <p class="mt-1 text-sm opacity-70">
          {{ t("tools.seqfetchCard") }}
        </p>
        <span class="mt-3 inline-block text-sm underline">{{ t("tools.open") }}</span>
      </RouterLink>

      <RouterLink
        to="/tools/exppattern"
        class="mt-4 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="exppattern-tool-link"
      >
        <h2 class="font-medium">{{ t("tools.exppattern.title") }}</h2>
        <p class="mt-1 text-sm opacity-70">
          {{ t("tools.exppatternCard") }}
        </p>
        <span class="mt-3 inline-block text-sm underline">{{ t("tools.open") }}</span>
      </RouterLink>

      <RouterLink
        to="/tools/enrichment"
        class="mt-4 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="enrichment-tool-link"
      >
        <h2 class="font-medium">{{ t("tools.enrichment.title") }}</h2>
        <p class="mt-1 text-sm opacity-70">
          {{ t("tools.enrichmentCard") }}
        </p>
        <span class="mt-3 inline-block text-sm underline">{{ t("tools.open") }}</span>
      </RouterLink>
    </div>
  </PortalLayout>
</template>
