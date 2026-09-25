<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  runExpPattern,
  type AssemblyInfo,
  type ExpPatternResponse,
} from "@soymutdb/api-client";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { assembliesQueryOptions } from "../lib/query-options";

const MAX_GENES = 50;
const genesRaw = ref("");
const assemblyId = ref("");
const scale = ref<"zscore" | "none">("zscore");
const clusterRows = ref(false);
const result = ref<ExpPatternResponse | null>(null);
const fieldError = ref("");

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed(() => toValue(assembliesQuery.data) ?? []);
const isAssembliesLoading = computed(() => toValue(assembliesQuery.isLoading));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));

watch(
  assemblies,
  (items: AssemblyInfo[]) => {
    if (assemblyId.value) return;
    const selected = items.find((item) => item.is_default) ?? items[0];
    if (selected) assemblyId.value = String(selected.id);
  },
  { immediate: true },
);

const patternMutation = useMutation({
  mutationFn: () =>
    runExpPattern({
      assembly_id: Number(assemblyId.value),
      genes: parseGenes(genesRaw.value),
      cluster_rows: clusterRows.value,
      scale: scale.value,
    }),
  onSuccess: (data) => {
    result.value = data;
  },
});

const isPending = computed(() => toValue(patternMutation.isPending));
const requestError = computed(() => toValue(patternMutation.error));
const hasData = computed(
  () =>
    result.value !== null &&
    result.value.conditions.length > 0 &&
    result.value.matrix.some((row) => row.some((value) => value !== null)),
);
const missingGenes = computed(() => result.value?.missing_genes ?? []);
const displayRows = computed(() => {
  const current = result.value;
  if (!current) return [];
  const indexes = current.row_order.length
    ? current.row_order
    : current.genes.map((_, index) => index);
  const rows: Array<{ gene: string; values: (number | null)[] }> = [];
  for (const index of indexes) {
    const gene = current.genes[index];
    if (!Number.isInteger(index) || index < 0 || gene === undefined) continue;
    rows.push({ gene, values: current.matrix[index] ?? [] });
  }
  return rows;
});

function parseGenes(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;]+/)
        .map((gene) => gene.trim())
        .filter(Boolean),
    ),
  ];
}

function selectAssembly(event: Event) {
  assemblyId.value = (event.target as HTMLSelectElement).value;
  result.value = null;
  fieldError.value = "";
  patternMutation.reset();
}

function submit() {
  const genes = parseGenes(genesRaw.value);
  if (!assemblyId.value) {
    fieldError.value = "Select an assembly.";
    return;
  }
  if (!genes.length) {
    fieldError.value = "Enter at least one gene ID.";
    return;
  }
  if (genes.length > MAX_GENES) {
    fieldError.value = `Enter no more than ${MAX_GENES} unique gene IDs.`;
    return;
  }
  fieldError.value = "";
  result.value = null;
  patternMutation.mutate();
}

function clear() {
  genesRaw.value = "";
  scale.value = "zscore";
  clusterRows.value = false;
  fieldError.value = "";
  result.value = null;
  patternMutation.reset();
}

function formatValue(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(2);
}

function cellStyle(value: number | null): Record<string, string> {
  if (value === null || !result.value) return {};
  const minimum = result.value.value_range[0] ?? null;
  const maximum = result.value.value_range[1] ?? null;
  if (minimum === null || maximum === null) return {};
  const ratio = maximum === minimum ? 0.5 : (value - minimum) / (maximum - minimum);
  const hue = Math.round(220 - Math.max(0, Math.min(1, ratio)) * 220);
  return { backgroundColor: `hsl(${hue} 75% 88%)` };
}

function onAssemblyChange(event: Event) {
  selectAssembly(event);
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main class="mx-auto grid max-w-7xl gap-8 p-6 md:p-8" data-testid="exppattern-page">
      <header class="grid gap-2">
        <RouterLink to="/tools" class="text-sm underline opacity-70">Research tools</RouterLink>
        <h1 class="text-2xl font-semibold">Expression pattern</h1>
        <p class="max-w-3xl text-sm opacity-75">
          Build an assembly-scoped gene-by-condition expression matrix with optional row
          standardization and clustering.
        </p>
      </header>

      <form class="grid gap-5 rounded-lg border p-5" @submit.prevent="submit">
        <div class="grid gap-2">
          <label for="exppattern-assembly" class="text-sm font-medium">Assembly</label>
          <select
            id="exppattern-assembly"
            class="rounded-md border bg-transparent p-2"
            :value="assemblyId"
            :disabled="isAssembliesLoading || isAssembliesError"
            aria-describedby="exppattern-assembly-status"
            data-testid="exppattern-assembly"
            @change="onAssemblyChange"
          >
            <option value="" disabled>Select an assembly</option>
            <option v-for="item in assemblies" :key="item.id" :value="item.id">
              {{ item.name }} · {{ item.version }}{{ item.is_default ? " (default)" : "" }}
            </option>
          </select>
          <p v-if="isAssembliesLoading" id="exppattern-assembly-status" role="status" class="text-sm opacity-70">
            Loading assemblies…
          </p>
          <p v-else-if="isAssembliesError" id="exppattern-assembly-status" role="alert" class="text-sm text-red-700">
            Assemblies could not be loaded. Retry after the connection is restored.
          </p>
          <p v-else id="exppattern-assembly-status" class="text-xs opacity-70">
            Gene identifiers and expression libraries are resolved only in this assembly.
          </p>
        </div>

        <div class="grid gap-2">
          <label for="exppattern-genes" class="text-sm font-medium">Gene IDs</label>
          <textarea
            id="exppattern-genes"
            v-model="genesRaw"
            rows="6"
            class="rounded-md border bg-transparent p-3 font-mono text-sm"
            placeholder="One gene ID per line, comma, or space"
            aria-describedby="exppattern-genes-hint exppattern-field-error"
            data-testid="exppattern-genes"
          />
          <p id="exppattern-genes-hint" class="text-xs opacity-70">Up to 50 unique gene IDs.</p>
          <p v-if="fieldError" id="exppattern-field-error" role="alert" class="text-sm text-red-700">
            {{ fieldError }}
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-5">
          <label class="grid gap-1 text-sm">
            <span>Row scaling</span>
            <select v-model="scale" class="rounded-md border bg-transparent p-2" data-testid="exppattern-scale">
              <option value="zscore">Z-score</option>
              <option value="none">Raw FPKM</option>
            </select>
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="clusterRows" type="checkbox" data-testid="exppattern-cluster" />
            Cluster rows
          </label>
        </div>

        <div class="flex flex-wrap gap-3">
          <button
            type="submit"
            class="rounded-md border px-4 py-2 font-medium disabled:opacity-50"
            :disabled="isPending || isAssembliesLoading || isAssembliesError"
            data-testid="exppattern-submit"
          >
            {{ isPending ? "Building matrix…" : "Build matrix" }}
          </button>
          <button type="button" class="rounded-md border px-4 py-2" data-testid="exppattern-clear" @click="clear">
            Clear
          </button>
        </div>
      </form>

      <section aria-live="polite" class="grid gap-4" data-testid="exppattern-result">
        <p v-if="isPending" role="status" data-testid="exppattern-loading">Loading expression data…</p>
        <div v-else-if="requestError" role="alert" class="grid gap-2 rounded-md border border-red-700 p-4" data-testid="exppattern-error">
          <p>The expression pattern could not be built.</p>
          <button type="button" class="w-fit underline" @click="submit">Retry</button>
        </div>
        <p v-else-if="!result" class="text-sm opacity-70" data-testid="exppattern-empty">
          Submit a gene list to build the matrix.
        </p>
        <article v-else class="grid gap-4 rounded-lg border p-5" data-testid="exppattern-summary">
          <header class="grid gap-1">
            <h2 class="text-lg font-semibold">Expression matrix</h2>
            <p class="text-sm opacity-75">
              {{ result.assembly_name }} · {{ result.assembly_version }} · release {{ result.release_id }} ·
              {{ result.genes.length }} genes × {{ result.conditions.length }} conditions
            </p>
            <p class="text-xs opacity-70">Scale: {{ result.scale }} · Row order: {{ result.clustering }}</p>
          </header>

          <div v-if="missingGenes.length" class="rounded-md border p-3 text-sm" data-testid="exppattern-missing">
            <p class="font-medium">No expression records for {{ missingGenes.length }} gene(s)</p>
            <p class="mt-1 break-words font-mono">{{ missingGenes.join(", ") }}</p>
          </div>
          <p v-if="!hasData" class="text-sm opacity-70" data-testid="exppattern-no-data">
            No requested genes have expression records in this assembly.
          </p>

          <div v-if="hasData" class="max-h-[65vh] overflow-auto rounded-md border">
            <table class="min-w-full border-collapse text-xs" aria-label="Assembly-scoped expression matrix">
              <thead class="sticky top-0 z-10 bg-white">
                <tr>
                  <th scope="col" class="sticky left-0 border-b bg-white p-2 text-left">Gene</th>
                  <th v-for="condition in result.conditions" :key="condition" scope="col" class="border-b p-2 text-right font-mono">
                    {{ condition }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in displayRows" :key="row.gene">
                  <th scope="row" class="sticky left-0 border-r bg-white p-2 text-left font-mono">{{ row.gene }}</th>
                  <td
                    v-for="(condition, columnIndex) in result.conditions"
                    :key="`${row.gene}-${condition}`"
                    class="border-b p-2 text-right font-mono tabular-nums"
                    :style="cellStyle(row.values[columnIndex] ?? null)"
                    :title="`${row.gene} · ${condition}: ${formatValue(row.values[columnIndex])}`"
                  >
                    {{ formatValue(row.values[columnIndex]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </main>
  </ConfigProvider>
</template>
