<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getReleaseProvenance, getReleases } from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Releases — where each published release came from.
 *
 * A release row is only half the record: an operator publishing data needs to
 * see the provenance (which imports, which source files) that produced it. The
 * provenance is fetched per release on demand rather than for every row, so
 * opening this page does not fan out into one request per release.
 */
const query = useQuery({
  queryKey: ["admin", "releases"],
  queryFn: () => getReleases({ page: 1, page_size: 100 }),
  staleTime: 30_000,
});

const releases = computed(() => toValue(query.data) ?? []);
const selectedId = ref<string | null>(null);

const provenanceQuery = useQuery({
  queryKey: computed(() => ["admin", "release-provenance", selectedId.value]),
  queryFn: () => getReleaseProvenance(selectedId.value as string),
  enabled: computed(() => Boolean(selectedId.value)),
  staleTime: 60_000,
});
const provenance = computed(() => toValue(provenanceQuery.data) ?? []);
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.releases") }}</h1>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="releases.length === 0" data-testid="releases-empty" class="mt-4 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <table v-else class="mt-4 w-full text-sm" data-testid="releases-table">
        <thead class="text-left opacity-60">
          <tr>
            <th scope="col" class="py-2">{{ t("releases.releaseName") }}</th>
            <th scope="col" class="py-2">{{ t("releases.status") }}</th>
            <th scope="col" class="py-2">{{ t("releases.assembly") }}</th>
            <th scope="col" class="py-2 text-right">{{ t("releases.variantCount") }}</th>
            <th scope="col" class="py-2">{{ t("common.actions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="release in releases" :key="String(release.id)" class="border-t" data-testid="release-row">
            <td class="py-2 font-mono">{{ release.id }}</td>
            <td class="py-2">{{ release.status }}</td>
            <td class="py-2 font-mono text-xs">{{ release.assembly_name }}</td>
            <td class="py-2 text-right">{{ formatNumber(release.variant_count) }}</td>
            <td class="py-2">
              <button
                type="button"
                class="underline"
                :data-testid="'release-provenance-' + release.id"
                @click="selectedId = String(release.id)"
              >
                {{ t("releases.provenance") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <section v-if="selectedId" class="mt-6" aria-labelledby="provenance-heading">
        <h2 id="provenance-heading" class="text-sm font-medium opacity-70">
          {{ t("releases.provenance") }} · <span class="font-mono">{{ selectedId }}</span>
        </h2>
        <p v-if="provenanceQuery.isPending.value" class="mt-2 text-sm opacity-70">
          {{ t("common.loading") }}
        </p>
        <p
          v-else-if="provenance.length === 0"
          data-testid="provenance-empty"
          class="mt-2 text-sm opacity-70"
        >
          {{ t("common.noData") }}
        </p>
        <ul v-else class="mt-2 grid gap-2" data-testid="provenance-list">
          <li v-for="item in provenance" :key="String(item.id)" class="rounded-md border p-3 text-sm">
            <p class="font-mono text-xs">{{ item.source_type }} · {{ item.source_name }}</p>
            <p v-if="item.version" class="mt-1 text-xs opacity-70">{{ item.version }}</p>
            <a
              v-if="item.source_url"
              :href="item.source_url"
              target="_blank"
              rel="noopener noreferrer"
              class="mt-1 inline-block text-xs underline"
            >
              {{ item.source_url }}
            </a>
          </li>
        </ul>
      </section>
    </div>
  </ConfigProvider>
</template>
