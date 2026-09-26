<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { AssemblyInfo, GeneSummary } from "@soymutdb/api-client";
import { compactGeneId, formatPosition, SOYBEAN_CHROMOSOMES } from "@soymutdb/shared/genomics";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { assembliesQueryOptions, geneListQueryOptions, GENE_LIST_PAGE_SIZE } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Gene index — server-side paginated gene list with filters.
 *
 * Every result-affecting filter lives in the URL (`q`, `chromosome`,
 * `biotype`, `page`, `sort_by`, `sort_dir`), so a reload, a back/forward, or a
 * shared link restores exactly the result set the user was looking at. The
 * assembly context is the currently selected one (the portal is otherwise
 * assembly-agnostic here); a release switch is carried by the request header
 * pinned in the site-context store.
 */
const BIOTYPES = [
  "protein_coding",
  "pseudogene",
  "tRNA",
  "rRNA",
  "miRNA",
  "lncRNA",
  "transposable_element",
] as const;
const SORTABLE = ["gene_id", "symbol", "variant_count"] as const;

type SortDir = "asc" | "desc";

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

interface GeneFilters {
  q: string;
  chromosome: string;
  biotype: string;
  page: number;
  sort_by: string;
  sort_dir: SortDir;
}

function readFilters(): GeneFilters {
  const query = route.query;
  const page = Number(query.page ?? 1);
  return {
    q: typeof query.q === "string" ? query.q : "",
    chromosome: typeof query.chromosome === "string" ? query.chromosome : "",
    biotype: typeof query.biotype === "string" ? query.biotype : "",
    page: Number.isInteger(page) && page > 0 ? page : 1,
    sort_by: typeof query.sort_by === "string" ? query.sort_by : "gene_id",
    sort_dir: query.sort_dir === "desc" ? "desc" : "asc",
  };
}

const filters = computed(readFilters);
const draft = reactive({ q: filters.value.q });
watch(filters, (value) => {
  draft.q = value.q;
});

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);
const activeAssemblyId = computed(() => {
  const key = site.assemblyKey;
  if (!key) return undefined;
  const match = assemblies.value.find((item) => item.name === key || String(item.id) === key);
  return match ? String(match.id) : undefined;
});

const query = useQuery(
  computed(() =>
    geneListQueryOptions({
      q: filters.value.q || undefined,
      chromosome: filters.value.chromosome || undefined,
      biotype: filters.value.biotype || undefined,
      assemblyId: activeAssemblyId.value ?? null,
      page: filters.value.page,
      pageSize: GENE_LIST_PAGE_SIZE,
      sortBy: filters.value.sort_by,
      sortDir: filters.value.sort_dir,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const items = computed<GeneSummary[]>(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));

function navigateWith(next: Partial<GeneFilters>) {
  const merged: GeneFilters = { ...filters.value, ...next, page: next.page ?? 1 };
  const params: Record<string, string> = {};
  if (merged.q) params.q = merged.q;
  if (merged.chromosome) params.chromosome = merged.chromosome;
  if (merged.biotype) params.biotype = merged.biotype;
  if (merged.page > 1) params.page = String(merged.page);
  if (merged.sort_by !== "gene_id") params.sort_by = merged.sort_by;
  if (merged.sort_dir !== "asc") params.sort_dir = merged.sort_dir;
  void router.push({ path: "/genes", query: params });
}

function sortDirection(column: string): "" | "asc" | "desc" {
  if (filters.value.sort_by !== column) return "";
  return filters.value.sort_dir === "asc" ? "asc" : "desc";
}

function toggleSort(column: string) {
  if (!SORTABLE.includes(column as (typeof SORTABLE)[number])) return;
  const nextDir: SortDir =
    filters.value.sort_by === column && filters.value.sort_dir === "asc" ? "desc" : "asc";
  navigateWith({ sort_by: column, sort_dir: nextDir });
}

function geneHref(row: GeneSummary): string {
  const params = new URLSearchParams();
  if (row.assembly_id) params.set("assembly", String(row.assembly_id));
  const suffix = params.toString();
  return suffix ? `/genes/${row.gene_id}?${suffix}` : `/genes/${row.gene_id}`;
}

const lastPage = computed(() => Math.max(1, Math.ceil(total.value / GENE_LIST_PAGE_SIZE)));
const activeFilterCount = computed(
  () => [filters.value.q, filters.value.chromosome, filters.value.biotype].filter(Boolean).length,
);
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("genes.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("genes.subtitle") }}</p>

      <form
        class="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        role="search"
        @submit.prevent="navigateWith({ q: draft.q.trim() })"
      >
        <label class="text-sm opacity-70">
          {{ t("genes.search") }}
          <input
            v-model="draft.q"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            :placeholder="t('genes.searchPlaceholder')"
            data-testid="genes-search"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("genes.chromosome") }}
          <select
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            :value="filters.chromosome || 'all'"
            data-testid="genes-chromosome"
            @change="navigateWith({ chromosome: ($event.target as HTMLSelectElement).value === 'all' ? '' : ($event.target as HTMLSelectElement).value })"
          >
            <option value="all">{{ t("genes.allChromosomes") }}</option>
            <option v-for="name in SOYBEAN_CHROMOSOMES" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("genes.biotype") }}
          <select
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            :value="filters.biotype || 'all'"
            data-testid="genes-biotype"
            @change="navigateWith({ biotype: ($event.target as HTMLSelectElement).value === 'all' ? '' : ($event.target as HTMLSelectElement).value })"
          >
            <option value="all">{{ t("genes.allBiotype") }}</option>
            <option v-for="name in BIOTYPES" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <div class="flex items-end gap-2">
          <Button html-type="submit" data-testid="genes-filter-apply">
            {{ t("common.search") }}
          </Button>
          <Button
            :disabled="activeFilterCount === 0"
            data-testid="genes-filter-clear"
            @click="navigateWith({ q: '', chromosome: '', biotype: '' })"
          >
            {{ t("common.clear") }}
          </Button>
        </div>
      </form>

      <div class="mt-6" role="region" :aria-label="t('genes.resultsAria')">
        <p v-if="isLoading" data-testid="genes-loading" class="text-sm opacity-70">
          {{ t("common.loading") }}
        </p>
        <p v-else-if="isError" data-testid="genes-error" class="text-sm text-red-700">
          {{ t("common.errorDescription") }}
        </p>
        <template v-else>
          <p class="mb-3 text-sm opacity-70" data-testid="genes-total">
            {{ total.toLocaleString() }} {{ t("common.total") }}
          </p>
          <p v-if="items.length === 0" data-testid="genes-empty" class="text-sm opacity-70">
            {{ t("genes.noResults") }}
          </p>
          <table v-else class="w-full text-sm" data-testid="genes-table">
            <thead class="text-left opacity-60">
              <tr>
                <th scope="col" class="py-2">
                  <button
                    type="button"
                    class="underline decoration-dotted"
                    :aria-sort="sortDirection('gene_id') === 'desc' ? 'descending' : 'ascending'"
                    data-testid="genes-sort-gene_id"
                    @click="toggleSort('gene_id')"
                  >
                    {{ t("genes.geneId") }}
                  </button>
                </th>
                <th scope="col" class="py-2">{{ t("genes.symbol") }}</th>
                <th scope="col" class="py-2">{{ t("genes.biotypeLabel") }}</th>
                <th scope="col" class="py-2">{{ t("genes.chromosomeLabel") }}</th>
                <th scope="col" class="py-2">{{ t("genes.position") }}</th>
                <th scope="col" class="py-2 text-right">
                  <button
                    type="button"
                    class="underline decoration-dotted"
                    data-testid="genes-sort-variant_count"
                    @click="toggleSort('variant_count')"
                  >
                    {{ t("genes.variantCount") }}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in items" :key="row.gene_id" data-testid="gene-row" class="border-t">
                <td class="py-2 font-mono">
                  <RouterLink :to="geneHref(row)" class="underline">
                    {{ compactGeneId(row.gene_id, 24) }}
                  </RouterLink>
                </td>
                <td class="py-2">{{ row.symbol ?? "—" }}</td>
                <td class="py-2 font-mono text-xs">{{ row.biotype }}</td>
                <td class="py-2 font-mono text-xs">{{ row.chromosome }}</td>
                <td class="py-2 font-mono text-xs">
                  {{ formatPosition(row.start_pos) }}–{{ formatPosition(row.end_pos) }}
                </td>
                <td class="py-2 text-right font-mono text-xs">
                  {{ row.variant_count == null ? "—" : row.variant_count.toLocaleString() }}
                </td>
              </tr>
            </tbody>
          </table>

          <nav class="mt-4 flex items-center gap-3" :aria-label="t('common.pagination')">
            <Button
              :disabled="filters.page <= 1"
              data-testid="genes-prev-page"
              @click="navigateWith({ page: filters.page - 1 })"
            >
              {{ t("common.previous") }}
            </Button>
            <span class="text-sm opacity-70" data-testid="genes-page">
              {{ t("common.page") }} {{ filters.page }} / {{ lastPage }}
            </span>
            <Button
              :disabled="filters.page >= lastPage"
              data-testid="genes-next-page"
              @click="navigateWith({ page: filters.page + 1 })"
            >
              {{ t("common.next") }}
            </Button>
          </nav>
        </template>
      </div>
    </div>
  </PortalLayout>
</template>
