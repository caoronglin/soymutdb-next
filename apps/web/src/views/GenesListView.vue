<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { AssemblyInfo, GeneSummary } from "@soymutdb/api-client";
import { compactGeneId, formatPosition, SOYBEAN_CHROMOSOMES } from "@soymutdb/shared/genomics";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import AppIcon from "../components/table/AppIcon.vue";
import DataTable from "../components/table/DataTable.vue";
import FilterCard from "../components/table/FilterCard.vue";
import FilterField from "../components/table/FilterField.vue";
import PageHeader from "../components/table/PageHeader.vue";
import type { TableColumn, TableSort } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import { t } from "../lib/i18n";
import { assembliesQueryOptions, geneListQueryOptions, GENE_LIST_PAGE_SIZE } from "../lib/query-options";
import { useSiteContent } from "../lib/site-content";
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

// Operator-editable page copy (admin `content.*` rows): override ?? localized fallback.
const { get } = useSiteContent();

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
const currentSort = computed<TableSort>(() => ({
  key: filters.value.sort_by,
  dir: filters.value.sort_dir,
}));

const columns = computed<TableColumn[]>(() => [
  {
    id: "gene_id",
    header: t("genes.geneId"),
    sortKey: "gene_id",
    sortTestId: "genes-sort-gene_id",
    primary: true,
    cellClass: "font-mono",
  },
  { id: "symbol", header: t("genes.symbol"), sortKey: "symbol" },
  { id: "biotype", header: t("genes.biotypeLabel"), cellClass: "font-mono text-xs" },
  { id: "chromosome", header: t("genes.chromosomeLabel"), cellClass: "font-mono text-xs" },
  { id: "position", header: t("genes.position"), cellClass: "font-mono text-xs" },
  {
    id: "variant_count",
    header: t("genes.variantCount"),
    sortKey: "variant_count",
    sortTestId: "genes-sort-variant_count",
    numeric: true,
    align: "right",
    cellClass: "font-mono text-xs",
  },
  { id: "actions", header: "", width: "48px" },
]);
</script>

<template>
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <PageHeader :eyebrow="get('genes.title', t('genes.title'))" :title="get('genes.subtitle', t('genes.subtitle'))" />

      <FilterCard @submit="navigateWith({ q: draft.q.trim() })">
        <FilterField :label="t('genes.search')" for-id="genes-search">
          <input
            id="genes-search"
            v-model="draft.q"
            class="w-full max-w-xs rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :placeholder="t('genes.searchPlaceholder')"
            data-testid="genes-search"
          />
        </FilterField>
        <FilterField :label="t('genes.chromosome')" for-id="genes-chromosome">
          <select
            id="genes-chromosome"
            class="w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :value="filters.chromosome || 'all'"
            data-testid="genes-chromosome"
            @change="navigateWith({ chromosome: ($event.target as HTMLSelectElement).value === 'all' ? '' : ($event.target as HTMLSelectElement).value })"
          >
            <option value="all">{{ t("genes.allChromosomes") }}</option>
            <option v-for="name in SOYBEAN_CHROMOSOMES" :key="name" :value="name">{{ name }}</option>
          </select>
        </FilterField>
        <FilterField :label="t('genes.biotype')" for-id="genes-biotype">
          <select
            id="genes-biotype"
            class="w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :value="filters.biotype || 'all'"
            data-testid="genes-biotype"
            @change="navigateWith({ biotype: ($event.target as HTMLSelectElement).value === 'all' ? '' : ($event.target as HTMLSelectElement).value })"
          >
            <option value="all">{{ t("genes.allBiotype") }}</option>
            <option v-for="name in BIOTYPES" :key="name" :value="name">{{ name }}</option>
          </select>
        </FilterField>

        <template #actions>
          <Button html-type="submit" data-testid="genes-filter-apply">
            {{ t("common.search") }}
          </Button>
          <Button
            :disabled="activeFilterCount === 0"
            data-testid="genes-filter-clear"
            @click="navigateWith({ q: '', chromosome: '', biotype: '' })"
          >
            <AppIcon name="reload" class="mr-1 inline size-3.5" />
            {{ t("common.clear") }}
          </Button>
        </template>
      </FilterCard>

      <div class="mt-4" role="region" :aria-label="t('genes.resultsAria')">
        <p class="mb-3 text-sm text-muted-foreground" data-testid="genes-total">
          {{ total.toLocaleString() }} {{ t("common.total") }}
        </p>

        <StateBlock
          v-if="isError"
          data-testid="genes-error"
          variant="error"
          :title="t('common.errorDescription')"
        />
        <StateBlock
          v-else-if="!isLoading && items.length === 0"
          data-testid="genes-empty"
          variant="empty"
          icon="dna"
          :title="t('genes.noResults')"
          :description="t('common.noResults')"
        />
        <DataTable
          v-else
          :data-testid="isLoading ? 'genes-loading' : 'genes-table'"
          :columns="columns"
          :rows="items"
          :loading="isLoading"
          :sort="currentSort"
          :aria-label="t('genes.resultsAria')"
          :row-key="(row) => row.gene_id"
          :row-attrs="() => ({ 'data-testid': 'gene-row' })"
          :emptyTitle="t('genes.noResults')"
          :emptyDescription="t('common.noResults')"
          @sort="toggleSort"
        >
          <template #cell-gene_id="{ row }">
            <RouterLink :to="geneHref(row)" class="link-underline font-medium text-primary">
              {{ compactGeneId(row.gene_id, 24) }}
            </RouterLink>
          </template>
          <template #cell-symbol="{ row }">{{ row.symbol ?? "—" }}</template>
          <template #cell-position="{ row }">
            {{ formatPosition(row.start_pos) }}–{{ formatPosition(row.end_pos) }}
          </template>
          <template #cell-variant_count="{ row }">
            {{ row.variant_count == null ? "—" : row.variant_count.toLocaleString() }}
          </template>
          <template #cell-actions="{ row }">
            <RouterLink
              :to="geneHref(row)"
              class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              :aria-label="`View ${row.gene_id}`"
            >
              <AppIcon name="arrow-right" class="size-4" />
            </RouterLink>
          </template>
        </DataTable>

        <nav
          v-if="!isError"
          class="mt-4 flex flex-wrap items-center gap-3"
          :aria-label="t('common.pagination')"
        >
          <Button
            :disabled="filters.page <= 1"
            data-testid="genes-prev-page"
            @click="navigateWith({ page: filters.page - 1 })"
          >
            {{ t("common.previous") }}
          </Button>
          <span class="text-sm text-muted-foreground" data-testid="genes-page">
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
      </div>
    </div>
  </PortalLayout>
</template>
