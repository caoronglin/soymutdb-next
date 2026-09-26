<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { AssemblyInfo, GeneSummary } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import ConfigurableTable, { type ConfigurableRow } from "../components/ConfigurableTable.vue";
import PortalLayout from "../components/PortalLayout.vue";
import { assemblyOptionLabel, resolveAssemblyParam } from "../lib/assembly-selection";
import { t } from "../lib/i18n";
import {
  assembliesQueryOptions,
  geneSearchQueryOptions,
  tableViewQueryOptions,
} from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Gene ID search — one of the portal's two primary entry points.
 *
 * Contract: the result view reads `q`, `assembly` and `run` from the URL. A
 * parameterized URL restores the form state and runs exactly once, so a shared
 * deep link reproduces the same assembly-scoped result set. Without an
 * assembly the request would be ambiguous across the v4/v5 coordinate
 * namespaces, so submit is disabled until an assembly is resolved
 * (DB-CORE-3/4) instead of silently defaulting to one.
 */


const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const initial = {
  q: typeof route.query.q === "string" ? route.query.q : "",
  assembly: typeof route.query.assembly === "string" ? route.query.assembly : "",
  run: route.query.run === "1" || route.query.run === "true",
};

const geneIdsRaw = ref(initial.q);
const draftAssemblyId = ref("");
const page = ref(1);
const submitted = ref<{ q: string; assemblyId: string } | null>(null);
let deepLinkConsumed = false;

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);
const isLoadingAssemblies = computed(() => toValue(assembliesQuery.isLoading));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));

const defaultAssembly = computed(
  () => assemblies.value.find((item) => item.is_default) ?? assemblies.value[0],
);

// The deep-link parameter is the stable id; a legacy name resolves once and is
// rewritten to the id. Unknown or shared names must not silently fall through
// to the default assembly (that queries another coordinate namespace).
const assemblyResolution = computed(() =>
  resolveAssemblyParam(assemblies.value, initial.assembly),
);
const unknownAssembly = computed(
  () =>
    assemblyResolution.value.status === "unknown" ||
    assemblyResolution.value.status === "ambiguous",
);
const formAssemblyId = computed(() => {
  if (draftAssemblyId.value) return draftAssemblyId.value;
  const resolution = assemblyResolution.value;
  if (resolution.status === "unknown" || resolution.status === "ambiguous") return "";
  const linked = resolution.status === "resolved" ? resolution.assembly : defaultAssembly.value;
  return linked ? String(linked.id) : "";
});

let canonicalized = false;
watch(
  [assemblyResolution, isLoadingAssemblies],
  ([resolution, loading]) => {
    if (canonicalized || loading) return;
    if (resolution.status !== "resolved" || resolution.via !== "name") return;
    canonicalized = true;
    void router.replace({
      path: route.path,
      query: { ...route.query, assembly: String(resolution.assembly.id) },
    });
  },
  { immediate: true },
);

/**
 * A deep link runs at most once, and only once its assembly can be resolved:
 * the assembly id (not the display name) is what the request and the result
 * label must agree on.
 */
watch(
  [formAssemblyId, isLoadingAssemblies],
  ([assemblyId, loading]) => {
    if (deepLinkConsumed || loading || !assemblyId) return;
    if (!initial.run && !initial.assembly) return;
    deepLinkConsumed = true;
    submitted.value = { q: geneIdsRaw.value.trim(), assemblyId };
  },
  { immediate: true },
);

const selectedAssembly = computed(() =>
  assemblies.value.find((item) => String(item.id) === submitted.value?.assemblyId),
);

// Column layout comes from the admin-managed template (docs/dev/configurable-table-views.md).
const tableView = useQuery(computed(() => tableViewQueryOptions("genes")));
const viewColumns = computed(() => toValue(tableView.data)?.columns ?? []);
const viewActions = computed(() => toValue(tableView.data)?.actions);

const query = useQuery(
  computed(() =>
    geneSearchQueryOptions({
      q: submitted.value?.q ?? null,
      assemblyId: submitted.value?.assemblyId ?? null,
      page: page.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const items = computed<GeneSummary[]>(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));

function submit() {
  const value = geneIdsRaw.value.trim();
  page.value = 1;
  submitted.value = value && formAssemblyId.value ? { q: value, assemblyId: formAssemblyId.value } : null;
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("search.genes.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("search.genes.subtitle") }}</p>

      <form
        class="mt-6 grid gap-4 sm:grid-cols-[2fr_1fr_auto] sm:items-end"
        role="search"
        @submit.prevent="submit"
      >
        <label class="text-sm opacity-70">
          {{ t("search.genes.geneId") }}
          <input
            v-model="geneIdsRaw"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono"
            :placeholder="t('search.genes.geneIdPlaceholder')"
            :aria-describedby="'search-genes-hint'"
            data-testid="search-genes-input"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("search.genes.assembly") }}
          <select
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            :value="formAssemblyId"
            :disabled="isLoadingAssemblies"
            data-testid="search-genes-assembly"
            @change="draftAssemblyId = ($event.target as HTMLSelectElement).value"
          >
            <option v-for="item in assemblies" :key="String(item.id)" :value="String(item.id)">
              {{ assemblyOptionLabel(item) }}{{ item.is_default ? " · default" : "" }}
            </option>
          </select>
        </label>
        <Button html-type="submit" :disabled="!formAssemblyId || unknownAssembly" data-testid="search-genes-submit">
          {{ t("search.genes.submit") }}
        </Button>
        <p id="search-genes-hint" class="text-xs opacity-60 sm:col-span-2">
          {{ t("search.genes.geneIdHint") }}
        </p>
      </form>

      <p v-if="isLoadingAssemblies" data-testid="search-genes-assemblies-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isAssembliesError" data-testid="search-genes-assemblies-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p
        v-else-if="unknownAssembly"
        role="alert"
        data-testid="search-genes-unknown-assembly"
        class="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {{ assemblyResolution.status === "ambiguous" ? t("common.ambiguousAssembly") : t("common.unknownAssembly") }}
      </p>

      <div class="mt-6" role="region" :aria-label="t('genes.resultsAria')">
        <p v-if="isLoading" data-testid="search-genes-loading" class="text-sm opacity-70">
          {{ t("common.loading") }}
        </p>
        <p v-else-if="isError" data-testid="search-genes-error" class="text-sm text-red-700">
          {{ t("common.errorDescription") }}
        </p>
        <p v-else-if="!submitted" data-testid="search-genes-idle" class="text-sm opacity-70">
          {{ t("search.genes.subtitle") }}
        </p>
        <template v-else>
          <p class="mb-3 text-sm opacity-70" data-testid="search-genes-total">
            {{ t("search.genes.resultsFor") }} {{ total.toLocaleString() }}
          </p>
          <!--
            The column set comes from the table-view template, so the rendered
            order is the configured one (assembly → chromosome → position →
            mutation feature → gene id, plus the optional JBrowse action). The
            table renders its headers even with zero rows: an empty column set
            would hide the fact that a column is missing rather than showing it
            as empty.
          -->
          <ConfigurableTable
            :columns="viewColumns"
            :actions="viewActions"
            :rows="items as unknown as ConfigurableRow[]"
            :assembly-name="selectedAssembly?.name ?? null"
            :caption="t('search.genes.subtitle')"
            data-testid="search-genes-table"
          />
          <p v-if="items.length === 0" data-testid="search-genes-empty" class="mt-3 text-sm opacity-70">
            {{ t("search.genes.noResults") }}
          </p>
        </template>
      </div>
    </div>
  </PortalLayout>
</template>
