<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { normalizeInterval } from "@soymutdb/genome-view-model";
import { formatPosition } from "@soymutdb/shared/genomics";
import { Button, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import AppIcon from "../components/table/AppIcon.vue";
import DataTable from "../components/table/DataTable.vue";
import FilterCard from "../components/table/FilterCard.vue";
import FilterField from "../components/table/FilterField.vue";
import PageHeader from "../components/table/PageHeader.vue";
import type { TableColumn } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import { assemblyOptionLabel, resolveAssemblyParam } from "../lib/assembly-selection";
import { t } from "../lib/i18n";
import { assembliesQueryOptions, variantsQueryOptions } from "../lib/query-options";
import { useSiteContent } from "../lib/site-content";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Variant explorer (Phase F).
 *
 * Filters are URL-backed state: /variants?assembly=5&chromosome=Chr01&...&cursor=...
 * survives reload, back/forward and sharing. The assembly parameter is the
 * stable catalogue id; the label-based backend filter is resolved at the
 * request boundary. An unknown or shared name is reported instead of falling
 * back to another coordinate namespace (DB-CORE-3/4). total_count is shown only
 * when the backend returns a real total; null means "hidden" (ADR-0006).
 */
const PAGE_SIZE = 50;
const VARIANT_TYPES = ["SNP", "INS", "DEL", "MNV", "SV"] as const;
const IMPACTS = ["HIGH", "MODERATE", "LOW", "MODIFIER"] as const;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

// Operator-editable page copy (admin `content.*` rows): override ?? localized fallback.
const { get } = useSiteContent();

interface VariantFiltersState {
  chromosome: string;
  variant_type: string;
  impact: string;
  mutant_line_id: string;
}

function readFilters(): VariantFiltersState {
  return {
    chromosome: typeof route.query.chromosome === "string" ? route.query.chromosome : "",
    variant_type: typeof route.query.variant_type === "string" ? route.query.variant_type : "",
    impact: typeof route.query.impact === "string" ? route.query.impact : "",
    mutant_line_id:
      typeof route.query.mutant_line_id === "string" ? route.query.mutant_line_id : "",
  };
}

const filters = computed(readFilters);
const draft = reactive({ ...readFilters() });
watch(filters, (value) => Object.assign(draft, value), { immediate: true, deep: true });

const assemblyParam = computed(() =>
  typeof route.query.assembly === "string" ? route.query.assembly : "",
);

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed(() => toValue(assembliesQuery.data) ?? []);
const isLoadingAssemblies = computed(() => toValue(assembliesQuery.isLoading));

// The URL holds the stable id. A unique legacy name resolves once and is
// rewritten to the id; unknown or shared names stay unresolved on purpose.
const assemblyResolution = computed(() =>
  resolveAssemblyParam(assemblies.value, assemblyParam.value),
);
const unknownAssembly = computed(
  () =>
    assemblyResolution.value.status === "unknown" ||
    assemblyResolution.value.status === "ambiguous",
);
const selectedAssembly = computed(() =>
  assemblyResolution.value.status === "resolved" ? assemblyResolution.value.assembly : null,
);
const selectedAssemblyId = computed(() =>
  selectedAssembly.value ? String(selectedAssembly.value.id) : "",
);
const selectedAssemblyName = computed(() => selectedAssembly.value?.name ?? null);

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

function parsedRegion(): { start?: number; end?: number } {
  const start = typeof route.query.start === "string" ? Number(route.query.start) : undefined;
  const end = typeof route.query.end === "string" ? Number(route.query.end) : undefined;
  if (start === undefined && end === undefined) return {};
  if (!start || !end || !Number.isInteger(start) || !Number.isInteger(end)) return {};
  try {
    const norm = normalizeInterval({
      assemblyKey: selectedAssemblyId.value || "?",
      start,
      end,
    });
    return { start: norm.start, end: norm.end };
  } catch {
    return {};
  }
}

// Cursor stack mirrors the React baseline: "previous" pops to the cursor that
// produced the current page, and any filter change resets to the first page.
// The reset watches the serialized filter identity, not `filters` itself:
// writing the cursor to the URL changes `route.query` and would otherwise
// reset the stack on every page turn.
const filterKey = computed(() => JSON.stringify(readFilters()));
const cursorStack = ref<Array<string | undefined>>([
  typeof route.query.cursor === "string" ? route.query.cursor : undefined,
]);
const cursor = computed(() => cursorStack.value[cursorStack.value.length - 1]);
watch(filterKey, () => {
  cursorStack.value = [undefined];
});

const query = useQuery(
  computed(() => ({
    ...variantsQueryOptions({
      assemblyId: selectedAssemblyId.value || null,
      assemblyName: selectedAssemblyName.value,
      chromosome: filters.value.chromosome || undefined,
      ...parsedRegion(),
      impact: filters.value.impact || undefined,
      variantType: filters.value.variant_type || undefined,
      mutantLinePublicId: filters.value.mutant_line_id || undefined,
      limit: PAGE_SIZE,
      page: cursorStack.value.length,
      cursor: cursor.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
    // An unresolved assembly must not fall through to an unfiltered request:
    // the page shows the explicit unknown/ambiguous error instead.
    enabled: !unknownAssembly.value,
  })),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const response = computed(() => toValue(query.data));
const items = computed(() => response.value?.items ?? []);
const totalCount = computed(() => response.value?.total_count ?? null);

// P1-05: with "All assemblies" selected every row must say which namespace it
// came from, because the same chromosome/position exists in v4 and v5.
const showAssemblyColumn = computed(() => !selectedAssemblyId.value);
function assemblyLabel(key: string | null | undefined): string {
  if (!key) return "—";
  const match = assemblies.value.find(
    (item) => item.name === key || item.version === key,
  );
  return match ? assemblyOptionLabel(match) : key;
}

function applyFilters(): void {
  const next: Record<string, string> = {};
  for (const key of ["chromosome", "variant_type", "impact", "mutant_line_id"] as const) {
    const value = draft[key].trim();
    if (value) next[key] = value;
  }
  if (assemblyParam.value) next.assembly = assemblyParam.value;
  const start = typeof route.query.start === "string" ? route.query.start : "";
  const end = typeof route.query.end === "string" ? route.query.end : "";
  if (start) next.start = start;
  if (end) next.end = end;
  cursorStack.value = [undefined];
  void router.replace({ path: route.path, query: next });
}

function selectAssembly(value: string): void {
  const next: Record<string, string> = { ...route.query } as Record<string, string>;
  if (value) next.assembly = value;
  else delete next.assembly;
  delete next.cursor;
  cursorStack.value = [undefined];
  void router.replace({ path: route.path, query: next });
}

function resetFilters(): void {
  cursorStack.value = [undefined];
  void router.replace({ path: route.path, query: {} });
}

function nextPage(): void {
  const next = response.value?.next_cursor;
  if (!next) return;
  cursorStack.value = [...cursorStack.value, next];
  void router.replace({ path: route.path, query: { ...route.query, cursor: next } });
}

function previousPage(): void {
  if (cursorStack.value.length <= 1) return;
  cursorStack.value = cursorStack.value.slice(0, -1);
  const next: Record<string, string> = { ...route.query } as Record<string, string>;
  const previous = cursor.value;
  if (previous) next.cursor = previous;
  else delete next.cursor;
  void router.replace({ path: route.path, query: next });
}

const hasActiveFilters = computed(() =>
  Boolean(
    filters.value.chromosome ||
      filters.value.variant_type ||
      filters.value.impact ||
      filters.value.mutant_line_id ||
      assemblyParam.value,
  ),
);

const columns = computed<TableColumn[]>(() => {
  const result: TableColumn[] = [
    { id: "variant_id", header: t("variants.variantId"), primary: true, cellClass: "font-mono text-xs" },
  ];
  if (showAssemblyColumn.value) {
    result.push({
      id: "assembly",
      header: t("variants.assembly"),
      headerTestId: "variants-assembly-column",
      cellClass: "text-xs",
    });
  }
  result.push(
    { id: "chromosome", header: t("variants.chromosomeLabel"), cellClass: "font-mono text-xs" },
    {
      id: "position",
      header: t("variants.positionLabel"),
      numeric: true,
      align: "right",
      cellClass: "font-mono text-xs",
    },
    { id: "ref_allele", header: t("variants.ref"), cellClass: "font-mono text-xs" },
    { id: "alt_allele", header: t("variants.alt"), cellClass: "font-mono text-xs" },
    { id: "variant_type", header: t("variants.variantTypeLabel"), cellClass: "text-xs" },
    { id: "impact", header: t("variants.impactLabel"), cellClass: "text-xs" },
    { id: "gene_symbol", header: t("variants.geneSymbol"), cellClass: "font-mono text-xs" },
  );
  return result;
});

function impactTone(impact: string): string {
  const tone =
    impact === "HIGH"
      ? "high"
      : impact === "MODERATE"
        ? "moderate"
        : impact === "LOW"
          ? "low"
          : "modifier";
  return `var(--impact-${tone})`;
}
</script>

<template>
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <PageHeader :eyebrow="get('variants.title', t('variants.title'))" :title="get('variants.subtitle', t('variants.subtitle'))">
        <template #actions>
          <Button data-testid="variants-export">
            <AppIcon name="download" class="mr-1.5 inline size-4" />
            {{ t("variants.export") }}
          </Button>
        </template>
      </PageHeader>

      <FilterCard @submit="applyFilters">
        <FilterField :label="t('variants.assembly')" for-id="variant-assembly-filter">
          <select
            id="variant-assembly-filter"
            class="w-full min-w-40 rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :value="selectedAssemblyId"
            :disabled="isLoadingAssemblies"
            data-testid="assembly-filter"
            @change="selectAssembly(($event.target as HTMLSelectElement).value)"
          >
            <option value="">{{ t("variants.allAssemblies") }}</option>
            <option v-for="item in assemblies" :key="String(item.id)" :value="String(item.id)">
              {{ assemblyOptionLabel(item) }}
            </option>
          </select>
        </FilterField>
        <FilterField :label="t('variants.chromosome')" for-id="variant-chromosome-filter">
          <input
            id="variant-chromosome-filter"
            v-model="draft.chromosome"
            class="w-full min-w-32 rounded-md border border-border bg-background px-3 py-2 font-mono outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="chromosome-filter"
            @change="applyFilters"
          />
        </FilterField>
        <FilterField :label="t('variants.variantType')" for-id="variant-type-filter">
          <select
            id="variant-type-filter"
            v-model="draft.variant_type"
            class="w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="variant-type-filter"
            @change="applyFilters"
          >
            <option value="">{{ t("variants.allTypes") }}</option>
            <option v-for="item in VARIANT_TYPES" :key="item" :value="item">{{ item }}</option>
          </select>
        </FilterField>
        <FilterField :label="t('variants.impact')" for-id="variant-impact-filter">
          <select
            id="variant-impact-filter"
            v-model="draft.impact"
            class="w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="impact-filter"
            @change="applyFilters"
          >
            <option value="">{{ t("variants.allImpacts") }}</option>
            <option v-for="item in IMPACTS" :key="item" :value="item">{{ item }}</option>
          </select>
        </FilterField>
        <FilterField :label="t('variants.mutantLine')" for-id="variant-mutant-line-filter">
          <input
            id="variant-mutant-line-filter"
            v-model="draft.mutant_line_id"
            class="w-full min-w-32 rounded-md border border-border bg-background px-3 py-2 font-mono outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="mutant-line-filter"
            @change="applyFilters"
          />
        </FilterField>

        <template #actions>
          <Button :disabled="!hasActiveFilters" data-testid="variants-filter-clear" @click="resetFilters">
            <AppIcon name="reload" class="mr-1.5 inline size-3.5" />
            {{ t("common.clear") }}
          </Button>
        </template>
      </FilterCard>

      <p
        v-if="unknownAssembly"
        role="alert"
        data-testid="variants-unknown-assembly"
        class="mt-4 flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
      >
        <AppIcon name="alert" class="mt-0.5 size-4" />
        <span>
          {{
            assemblyResolution.status === "ambiguous"
              ? t("common.ambiguousAssembly")
              : t("common.unknownAssembly")
          }}
        </span>
      </p>

      <section
        v-if="!unknownAssembly"
        data-testid="variants-results"
        class="mt-4"
        role="region"
        :aria-label="t('variants.resultsAria')"
      >
        <p class="mb-3 text-sm text-muted-foreground" data-testid="variants-total">
          <template v-if="totalCount !== null">
            {{ t("variants.totalCount", { count: totalCount }) }}
          </template>
          <template v-else>{{ t("variants.totalHidden") }}</template>
        </p>

        <StateBlock
          v-if="isError"
          data-testid="variants-error"
          variant="error"
          :title="t('variants.loadError')"
        />
        <StateBlock
          v-else-if="!isLoading && items.length === 0"
          data-testid="variants-empty"
          variant="empty"
          icon="dna"
          :title="t('variants.noResults')"
          :description="t('common.noResults')"
        />
        <DataTable
          v-else
          :data-testid="isLoading ? 'variants-loading' : 'variants-table'"
          :columns="columns"
          :rows="items"
          :loading="isLoading"
          :row-key="(row) => row.variant_id"
          :row-attrs="() => ({ 'data-testid': 'variant-row' })"
          :aria-label="t('variants.resultsAria')"
          :emptyTitle="t('variants.noResults')"
          :emptyDescription="t('common.noResults')"
        >
          <template #cell-assembly="{ row }">
            <span data-testid="variant-assembly">{{ assemblyLabel(row.assembly) }}</span>
          </template>
          <template #cell-position="{ row }">{{ formatPosition(row.position) }}</template>
          <template #cell-variant_type="{ row }">
            <Tag class="font-mono text-[10px]">{{ row.variant_type }}</Tag>
          </template>
          <template #cell-impact="{ row }">
            <span v-if="row.impact" class="inline-flex items-center gap-1.5">
              <span
                class="size-2 rounded-full"
                :style="{ backgroundColor: impactTone(row.impact) }"
                aria-hidden="true"
              />
              <span class="font-mono">{{ row.impact }}</span>
            </span>
            <span v-else class="text-muted-foreground">—</span>
          </template>
          <template #cell-gene_symbol="{ row }">
            <span v-if="row.gene_symbol || row.gene_id">{{ row.gene_symbol ?? row.gene_id }}</span>
            <span v-else class="text-muted-foreground">—</span>
          </template>
        </DataTable>

        <div v-if="!isError" class="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="inline-flex min-h-10 items-center gap-1 rounded-md border border-border px-3 text-sm disabled:opacity-50"
            :disabled="cursorStack.length <= 1"
            data-testid="variants-previous"
            @click="previousPage"
          >
            <AppIcon name="chevron-left" class="size-4" />
            {{ t("variants.previousPage") }}
          </button>
          <button
            type="button"
            class="inline-flex min-h-10 items-center gap-1 rounded-md border border-border px-3 text-sm disabled:opacity-50"
            :disabled="!response?.has_more || !response?.next_cursor"
            data-testid="variants-next"
            @click="nextPage"
          >
            {{ t("variants.nextPage") }}
            <AppIcon name="chevron-right" class="size-4" />
          </button>
          <span class="text-xs text-muted-foreground" data-testid="variants-page">
            {{ t("variants.pageOf", { page: cursorStack.length }) }}
          </span>
        </div>
      </section>
    </div>
  </PortalLayout>
</template>
