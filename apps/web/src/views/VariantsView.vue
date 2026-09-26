<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { normalizeInterval } from "@soymutdb/genome-view-model";
import { ConfigProvider, createThemeConfig, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { assemblyOptionLabel, resolveAssemblyParam } from "../lib/assembly-selection";
import { t } from "../lib/i18n";
import { assembliesQueryOptions, variantsQueryOptions } from "../lib/query-options";
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
      mutantLineId: filters.value.mutant_line_id || undefined,
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
</script>

<template>
  <PortalLayout>
    <ConfigProvider :theme="createThemeConfig({ dark: false })">
      <div class="mx-auto max-w-6xl px-4 py-8">
        <h1 class="text-2xl font-semibold">{{ t("variants.title") }}</h1>
        <p class="mt-1 text-sm opacity-70">{{ t("variants.subtitle") }}</p>

        <form
          class="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5"
          role="search"
          @submit.prevent="applyFilters"
        >
          <label class="text-sm opacity-70">
            {{ t("variants.assembly") }}
            <select
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
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
          </label>
          <label class="text-sm opacity-70">
            {{ t("variants.chromosome") }}
            <input
              v-model="draft.chromosome"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
              data-testid="chromosome-filter"
              @change="applyFilters"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("variants.variantType") }}
            <select
              v-model="draft.variant_type"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
              data-testid="variant-type-filter"
              @change="applyFilters"
            >
              <option value="">{{ t("variants.allTypes") }}</option>
              <option v-for="item in VARIANT_TYPES" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="text-sm opacity-70">
            {{ t("variants.impact") }}
            <select
              v-model="draft.impact"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
              data-testid="impact-filter"
              @change="applyFilters"
            >
              <option value="">{{ t("variants.allImpacts") }}</option>
              <option v-for="item in IMPACTS" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="text-sm opacity-70">
            {{ t("variants.mutantLine") }}
            <input
              v-model="draft.mutant_line_id"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono"
              data-testid="mutant-line-filter"
              @change="applyFilters"
            />
          </label>
        </form>

        <p
          v-if="unknownAssembly"
          role="alert"
          data-testid="variants-unknown-assembly"
          class="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {{ assemblyResolution.status === "ambiguous" ? t("common.ambiguousAssembly") : t("common.unknownAssembly") }}
        </p>

        <div v-if="isLoading" data-testid="variants-loading" class="mt-6 grid gap-2">
          <div v-for="index in 4" :key="index" class="h-10 w-full rounded bg-muted" />
        </div>
        <div
          v-else-if="isError"
          data-testid="variants-error"
          class="mt-6 rounded border border-red-300 p-5"
        >
          <p class="font-medium">{{ t("variants.loadError") }}</p>
        </div>

        <section v-else data-testid="variants-results" class="mt-6" :aria-label="t('variants.resultsAria')">
          <p class="mb-3 text-sm opacity-70" data-testid="variants-total">
            <template v-if="totalCount !== null">
              {{ t("variants.totalCount", { count: totalCount }) }}
            </template>
            <template v-else>{{ t("variants.totalHidden") }}</template>
          </p>
          <p v-if="items.length === 0" data-testid="variants-empty" class="text-sm opacity-70">
            {{ t("variants.noResults") }}
          </p>
          <table v-else class="w-full text-sm">
            <thead class="text-left opacity-60">
              <tr>
                <th scope="col" class="py-2">{{ t("variants.variantId") }}</th>
                <th v-if="showAssemblyColumn" scope="col" class="py-2" data-testid="variants-assembly-column">
                  {{ t("variants.assembly") }}
                </th>
                <th scope="col" class="py-2">{{ t("variants.chromosomeLabel") }}</th>
                <th scope="col" class="py-2">{{ t("variants.positionLabel") }}</th>
                <th scope="col" class="py-2">{{ t("variants.ref") }}</th>
                <th scope="col" class="py-2">{{ t("variants.alt") }}</th>
                <th scope="col" class="py-2">{{ t("variants.geneSymbol") }}</th>
                <th scope="col" class="py-2">{{ t("variants.impactLabel") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="variant in items" :key="variant.variant_id" class="border-t border-border" data-testid="variant-row">
                <td class="py-2 font-mono">{{ variant.variant_id }}</td>
                <td v-if="showAssemblyColumn" class="py-2" data-testid="variant-assembly">
                  {{ assemblyLabel(variant.assembly) }}
                </td>
                <td class="py-2">{{ variant.chromosome }}</td>
                <td class="py-2">{{ variant.position }}</td>
                <td class="py-2 font-mono">{{ variant.ref_allele }}</td>
                <td class="py-2 font-mono">{{ variant.alt_allele }}</td>
                <td class="py-2">{{ variant.gene_symbol ?? variant.gene_id ?? "—" }}</td>
                <td class="py-2"><Tag>{{ variant.impact ?? "—" }}</Tag></td>
              </tr>
            </tbody>
          </table>

          <div class="mt-4 flex items-center gap-3">
            <button
              type="button"
              class="min-h-10 rounded-md border border-border px-3 text-sm disabled:opacity-50"
              :disabled="cursorStack.length <= 1"
              data-testid="variants-previous"
              @click="previousPage"
            >
              {{ t("variants.previousPage") }}
            </button>
            <button
              type="button"
              class="min-h-10 rounded-md border border-border px-3 text-sm disabled:opacity-50"
              :disabled="!response?.has_more || !response?.next_cursor"
              data-testid="variants-next"
              @click="nextPage"
            >
              {{ t("variants.nextPage") }}
            </button>
            <span class="text-xs opacity-60" data-testid="variants-page">
              {{ t("variants.pageOf", { page: cursorStack.length }) }}
            </span>
          </div>
        </section>
      </div>
    </ConfigProvider>
  </PortalLayout>
</template>
