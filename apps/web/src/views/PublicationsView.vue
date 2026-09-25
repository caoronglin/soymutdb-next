<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import { listPublications, type Publication } from "@soymutdb/api-client";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";

/**
 * Publications — the citable record set.
 *
 * The list is server-provided and ordered, so the citation order in the UI is
 * the order the backend returns (no client-side re-ranking).
 */
const query = useQuery({
  queryKey: ["publications", "list"],
  queryFn: () => listPublications(),
  staleTime: 5 * 60_000,
});

const items = computed<Publication[]>(() => toValue(query.data) ?? []);
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-4xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("publications.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("publications.subtitle") }}</p>

      <p v-if="isPending" data-testid="publications-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isError" data-testid="publications-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="items.length === 0" data-testid="publications-empty" class="mt-6 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <ol v-else class="mt-6 grid gap-4" data-testid="publications-list">
        <li
          v-for="item in items"
          :key="String(item.id)"
          class="rounded-lg border p-4"
          data-testid="publication-row"
        >
          <h2 class="font-medium">{{ item.title }}</h2>
          <p v-if="item.authors" class="mt-1 text-sm opacity-70">{{ item.authors }}</p>
          <p class="mt-1 text-sm opacity-70">
            <span v-if="item.journal">{{ item.journal }}</span>
            <span v-if="item.year"> · {{ item.year }}</span>
          </p>
          <p v-if="item.doi" class="mt-1 font-mono text-xs opacity-70">DOI: {{ item.doi }}</p>
        </li>
      </ol>
    </div>
  </PortalLayout>
</template>
