<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute } from "vue-router";

import type {
  AssemblyInfo,
  ChromosomeInfo,
  VariantSummary,
} from "@soymutdb/api-client";

import { Button } from "@soymutdb/ui-vue";

import ConfigurableTable, { type ConfigurableRow } from "../components/ConfigurableTable.vue";
import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import {
  assembliesQueryOptions,
  assemblyChromosomesQueryOptions,
  regionVariantsQueryOptions,
  tableViewQueryOptions,
  REGION_SEARCH_MAX_RESULTS,
} from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Physical location search — the portal's other primary entry point.
 *
 * Region + assembly is the minimum unambiguous request: coordinates are only
 * meaningful inside one assembly namespace (DB-CORE-4), so the chromosome list
 * is fetched for the selected assembly and an out-of-list chromosome is
 * rejected rather than guessed.
 */


const route = useRoute();
const site = useSiteContextStore();

const initial = {
  assembly: typeof route.query.assembly === "string" ? route.query.assembly : "",
  chromosome: typeof route.query.chromosome === "string" ? route.query.chromosome : "",
  start: route.query.start ? Number(route.query.start) : undefined,
  end: route.query.end ? Number(route.query.end) : undefined,
  run: route.query.run === "1" || route.query.run === "true",
};

const draftAssemblyId = ref("");
const chromosome = ref(initial.chromosome);
const start = ref(initial.start ? String(initial.start) : "");
const end = ref(initial.end ? String(initial.end) : "");
const region = ref("");
let deepLinkConsumed = false;

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);
const isLoadingAssemblies = computed(() => toValue(assembliesQuery.isLoading));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));

const defaultAssembly = computed(
  () => assemblies.value.find((item) => item.is_default) ?? assemblies.value[0],
);
const linkedAssembly = computed(() =>
  assemblies.value.find(
    (item) => String(item.id) === initial.assembly || item.name === initial.assembly,
  ),
);
const formAssemblyId = computed(() => {
  if (draftAssemblyId.value) return draftAssemblyId.value;
  const linked = linkedAssembly.value ?? defaultAssembly.value;
  return linked ? String(linked.id) : "";
});

const chromosomesQuery = useQuery(
  computed(() =>
    assemblyChromosomesQueryOptions({ assemblyId: formAssemblyId.value || null }),
  ),
);

const chromosomes = computed<ChromosomeInfo[]>(() => toValue(chromosomesQuery.data) ?? []);

// Drop a deep-linked chromosome the selected assembly does not have, instead of
// silently requesting coordinates from another namespace.
watch(
  [chromosomes, () => toValue(chromosomesQuery.isLoading)],
  ([list, loading]) => {
    if (loading || !chromosome.value) return;
    if (list.length > 0 && !list.some((item) => item.name === chromosome.value)) {
      chromosome.value = "";
    }
  },
);

const selectedAssembly = computed(() =>
  assemblies.value.find((item) => String(item.id) === formAssemblyId.value),
);

/**
 * A deep link (`?run=1`) runs exactly once, and only once the assembly and its
 * chromosome list are known: the request needs the assembly *name* and a
 * chromosome that exists in that assembly's namespace.
 */
watch(
  [formAssemblyId, chromosomes, () => toValue(chromosomesQuery.isLoading)],
  ([assemblyId, list, loading]) => {
    if (deepLinkConsumed || !initial.run || loading || !assemblyId) return;
    if (list.length === 0 || !chromosome.value) return;
    deepLinkConsumed = true;
    runRegion();
  },
  { immediate: true },
);

const query = useQuery(
  computed(() =>
    regionVariantsQueryOptions({
      assemblyName: selectedAssembly.value?.name ?? null,
      chromosome: region.value || null,
      start: start.value ? Number(start.value) : null,
      end: end.value ? Number(end.value) : null,
      maxResults: REGION_SEARCH_MAX_RESULTS,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const items = computed<VariantSummary[]>(() => toValue(query.data) ?? []);

// Column layout comes from the admin-managed template, so the rendered table is
// the configured one — including any cross-assembly homolog columns the
// deployment has opted into.
const tableView = useQuery(computed(() => tableViewQueryOptions("variants")));
const viewColumns = computed(() => toValue(tableView.data)?.columns ?? []);
const viewActions = computed(() => toValue(tableView.data)?.actions);
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));

/**
 * Validate and run the region request. Returns false when the range or the
 * chromosome is invalid, which is what both the submit handler and the deep-link
 * runner use to reject a request instead of issuing an ambiguous one.
 */
function runRegion(): boolean {
  const parsedStart = Number(start.value);
  const parsedEnd = Number(end.value);
  if (!chromosome.value.trim() || !Number.isInteger(parsedStart) || parsedStart < 1) return false;
  if (!Number.isInteger(parsedEnd) || parsedEnd < parsedStart) return false;
  if (
    chromosomes.value.length > 0 &&
    !chromosomes.value.some((item) => item.name === chromosome.value.trim())
  ) {
    return false;
  }
  region.value = chromosome.value.trim();
  return true;
}

function submit() {
  runRegion();
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("search.location.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("search.location.subtitle") }}</p>

      <form
        class="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
        role="search"
        @submit.prevent="submit"
      >
        <label class="text-sm opacity-70">
          {{ t("search.location.assembly") }}
          <select
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            :value="formAssemblyId"
            :disabled="isLoadingAssemblies"
            data-testid="location-assembly"
            @change="draftAssemblyId = ($event.target as HTMLSelectElement).value"
          >
            <option v-for="item in assemblies" :key="String(item.id)" :value="String(item.id)">
              {{ item.name }}{{ item.is_default ? " · default" : "" }}
            </option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("search.location.chromosome") }}
          <select
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            v-model="chromosome"
            data-testid="location-chromosome"
          >
            <option value="" disabled>{{ t("common.selectAll") }}</option>
            <option v-for="item in chromosomes" :key="item.name" :value="item.name">
              {{ item.name }}
            </option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("search.location.start") }}
          <input
            v-model="start"
            type="number"
            min="1"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono"
            data-testid="location-start"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("search.location.end") }}
          <input
            v-model="end"
            type="number"
            min="1"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono"
            data-testid="location-end"
          />
        </label>
        <Button html-type="submit" :disabled="!formAssemblyId" data-testid="location-submit">
          {{ t("search.location.submit") }}
        </Button>
      </form>
      <p class="mt-2 text-xs opacity-60">{{ t("search.location.formatHint") }}</p>

      <p v-if="isAssembliesError" data-testid="location-assemblies-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>

      <div class="mt-6" role="region" aria-label="Region search results">
        <p v-if="isLoading" data-testid="location-loading" class="text-sm opacity-70">
          {{ t("common.loading") }}
        </p>
        <p v-else-if="isError" data-testid="location-error" class="text-sm text-red-700">
          {{ t("common.errorDescription") }}
        </p>
        <p v-else-if="!region" data-testid="location-idle" class="text-sm opacity-70">
          {{ t("search.location.formatHint") }}
        </p>
        <template v-else>
          <p class="mb-3 text-sm opacity-70" data-testid="location-total">
            {{ t("search.location.found", { count: items.length }) }}
          </p>
          <p v-if="items.length === 0" data-testid="location-empty" class="text-sm opacity-70">
            {{ t("search.location.noResults") }}
          </p>
          <ConfigurableTable
            v-else
            :columns="viewColumns"
            :actions="viewActions"
            :rows="items as unknown as ConfigurableRow[]"
            :assembly-name="selectedAssembly?.name ?? null"
            :caption="t('search.location.subtitle')"
            data-testid="location-table"
          />
        </template>
      </div>
    </div>
  </PortalLayout>
</template>
