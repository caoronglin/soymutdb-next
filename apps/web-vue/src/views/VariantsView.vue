<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { normalizeInterval } from "@soymutdb/genome-view-model";
import { ConfigProvider, Input, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { variantsQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

// Variant explorer (Phase F). Region + filters → searchVariants, with the
// release/assembly/site-scoped cache key and every result-affecting filter in
// the key (DB-CORE-6). The filters are URL-backed state: /variants?chromosome=
// Chr01&start=... survives reload, back/forward, and sharing (plan.md §17).
// Coordinates are validated/normalised through the neutral genome-view-model and
// scoped to the selected assembly (DB-CORE-3/4). total_count is shown only when
// the backend returns a real total; null means "hidden" (ADR-0006).
const VARIANT_LIMIT = 50;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const filters = computed(() => ({
  assembly: route.query.assembly ? String(route.query.assembly) : "",
  chromosome: route.query.chromosome ? String(route.query.chromosome) : "",
  start: route.query.start ? String(route.query.start) : "",
  end: route.query.end ? String(route.query.end) : "",
  impact: route.query.impact ? String(route.query.impact) : "",
}));

// Draft inputs are committed to the URL on submit/change, so a half-typed
// coordinate never becomes cache identity (and back/forward restores it).
const draft = reactive({ ...filters.value });
watch(
  filters,
  (value) => Object.assign(draft, value),
  { immediate: true, deep: true },
);

function parsedRegion(): { start?: number; end?: number } {
  const start = filters.value.start ? Number(filters.value.start) : undefined;
  const end = filters.value.end ? Number(filters.value.end) : undefined;
  if (start === undefined && end === undefined) return {};
  if (!start || !end || !Number.isInteger(start) || !Number.isInteger(end)) return {};
  try {
    const norm = normalizeInterval({ assemblyKey: filters.value.assembly || "?", start, end });
    return { start: norm.start, end: norm.end };
  } catch {
    return {};
  }
}

const query = useQuery(
  computed(() =>
    variantsQueryOptions({
      assemblyId: filters.value.assembly || null,
      chromosome: filters.value.chromosome || undefined,
      ...parsedRegion(),
      impact: filters.value.impact || undefined,
      limit: VARIANT_LIMIT,
      page: 1,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const response = computed(() => toValue(query.data));
const items = computed(() => response.value?.items ?? []);
const totalCount = computed(() => response.value?.total_count ?? null);

function applyFilters() {
  const next: Record<string, string> = {};
  for (const key of ["assembly", "chromosome", "start", "end", "impact"] as const) {
    const value = draft[key].trim();
    if (value) next[key] = value;
  }
  void router.replace({ path: "/variants", query: next });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-4xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/" class="underline">Home</RouterLink></p>
      <h1 class="mt-2 text-2xl font-semibold">Variants</h1>

      <form class="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5" role="search" @submit.prevent="applyFilters">
        <label class="text-sm opacity-70">Assembly
          <Input v-model="draft.assembly" placeholder="5" data-testid="assembly-filter" @change="applyFilters" />
        </label>
        <label class="text-sm opacity-70">Chromosome
          <Input v-model="draft.chromosome" placeholder="Chr01" data-testid="chromosome-filter" @change="applyFilters" />
        </label>
        <label class="text-sm opacity-70">Start
          <Input v-model="draft.start" placeholder="1" data-testid="start-filter" @change="applyFilters" />
        </label>
        <label class="text-sm opacity-70">End
          <Input v-model="draft.end" placeholder="1000000" data-testid="end-filter" @change="applyFilters" />
        </label>
        <label class="text-sm opacity-70">Impact
          <Input v-model="draft.impact" placeholder="HIGH" data-testid="impact-filter" @change="applyFilters" />
        </label>
      </form>

      <div v-if="isLoading" data-testid="variants-loading" class="mt-6 grid gap-2">
        <div v-for="index in 4" :key="index" class="h-10 w-full rounded bg-black/5" />
      </div>
      <div v-else-if="isError" data-testid="variants-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">Could not load variants.</p>
      </div>

      <section v-else data-testid="variants-results" class="mt-6" aria-label="Variant results">
        <p class="mb-3 text-sm opacity-70" data-testid="variants-total">
          <template v-if="totalCount !== null">{{ totalCount }} variants</template>
          <template v-else>Results shown per page (total hidden)</template>
        </p>
        <p v-if="items.length === 0" data-testid="variants-empty" class="text-sm opacity-70">
          No variants matched these filters.
        </p>
        <table v-else class="w-full text-sm">
          <thead class="text-left opacity-60">
            <tr><th>Variant</th><th>Location</th><th>Change</th><th>Gene</th><th>Impact</th></tr>
          </thead>
          <tbody>
            <tr v-for="variant in items" :key="variant.variant_id" data-testid="variant-row">
              <td class="font-mono">{{ variant.variant_id }}</td>
              <td>{{ variant.chromosome }}:{{ variant.position }}</td>
              <td class="font-mono">{{ variant.ref_allele }}→{{ variant.alt_allele }}</td>
              <td>{{ variant.gene_symbol ?? variant.gene_id ?? "—" }}</td>
              <td><Tag>{{ variant.impact ?? "—" }}</Tag></td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </ConfigProvider>
</template>
