<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  runExpPattern,
  type AssemblyInfo,
  type ExpPatternResponse,
} from "@soymutdb/api-client";

import PortalLayout from "../components/PortalLayout.vue";
import { assembliesQueryOptions } from "../lib/query-options";
import { t } from "../lib/i18n";

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

function scaleLabel(value: string): string {
  if (value === "zscore") return t("tools.exppattern.scaleZscore");
  if (value === "none") return t("tools.exppattern.scaleRaw");
  return value;
}

function clusteringLabel(value: string): string {
  return value && value !== "none"
    ? t("tools.exppattern.clusteringBadge")
    : t("tools.exppattern.clusteringNone");
}

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
    fieldError.value = t("tools.exppattern.errorAssemblyRequired");
    return;
  }
  if (!genes.length) {
    fieldError.value = t("tools.exppattern.errorGenesRequired");
    return;
  }
  if (genes.length > MAX_GENES) {
    fieldError.value = t("tools.exppattern.errorGenesMaxUnique", { max: MAX_GENES });
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
  <PortalLayout>
    <div class="mx-auto grid max-w-7xl gap-8 px-4 py-8" data-testid="exppattern-page">
      <header class="grid gap-2">
        <RouterLink to="/tools" class="text-sm underline opacity-70">{{ t("home.tasks") }}</RouterLink>
        <h1 class="text-2xl font-semibold">{{ t("tools.exppattern.title") }}</h1>
        <p class="max-w-3xl text-sm opacity-75">
          {{ t("tools.exppattern.subtitle") }}
        </p>
      </header>

      <form class="grid gap-5 rounded-lg border p-5" @submit.prevent="submit">
        <div class="grid gap-2">
          <label for="exppattern-assembly" class="text-sm font-medium">{{ t("tools.exppattern.assemblyLabel") }}</label>
          <select
            id="exppattern-assembly"
            class="rounded-md border bg-transparent p-2"
            :value="assemblyId"
            :disabled="isAssembliesLoading || isAssembliesError"
            aria-describedby="exppattern-assembly-status"
            data-testid="exppattern-assembly"
            @change="onAssemblyChange"
          >
            <option value="" disabled>{{ t("tools.exppattern.assemblyPlaceholder") }}</option>
            <option v-for="item in assemblies" :key="item.id" :value="item.id">
              {{ item.name }} · {{ item.version }}{{ item.is_default ? " (default)" : "" }}
            </option>
          </select>
          <p v-if="isAssembliesLoading" id="exppattern-assembly-status" role="status" class="text-sm opacity-70">
            {{ t("tools.exppattern.loadingAssemblies") }}
          </p>
          <p v-else-if="isAssembliesError" id="exppattern-assembly-status" role="alert" class="text-sm text-red-700">
            {{ t("tools.exppattern.assembliesError") }}
          </p>
          <p v-else id="exppattern-assembly-status" class="text-xs opacity-70">
            {{ t("tools.exppattern.assemblyHelp") }}
          </p>
        </div>

        <div class="grid gap-2">
          <label for="exppattern-genes" class="text-sm font-medium">{{ t("tools.exppattern.genesLabel") }}</label>
          <textarea
            id="exppattern-genes"
            v-model="genesRaw"
            rows="6"
            class="rounded-md border bg-transparent p-3 font-mono text-sm"
            :placeholder="t('tools.exppattern.genesPlaceholder')"
            aria-describedby="exppattern-genes-hint exppattern-field-error"
            data-testid="exppattern-genes"
          />
          <p id="exppattern-genes-hint" class="text-xs opacity-70">{{ t("tools.exppattern.genesLimit") }}</p>
          <p v-if="fieldError" id="exppattern-field-error" role="alert" class="text-sm text-red-700">
            {{ fieldError }}
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-5">
          <label class="grid gap-1 text-sm">
            <span>{{ t("tools.exppattern.scaleLabel") }}</span>
            <select v-model="scale" class="rounded-md border bg-transparent p-2" data-testid="exppattern-scale">
              <option value="zscore">{{ t("tools.exppattern.scaleZscore") }}</option>
              <option value="none">{{ t("tools.exppattern.scaleRaw") }}</option>
            </select>
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="clusterRows" type="checkbox" data-testid="exppattern-cluster" />
            {{ t("tools.exppattern.clusterLabel") }}
          </label>
        </div>

        <div class="flex flex-wrap gap-3">
          <button
            type="submit"
            class="rounded-md border px-4 py-2 font-medium disabled:opacity-50"
            :disabled="isPending || isAssembliesLoading || isAssembliesError"
            data-testid="exppattern-submit"
          >
            {{ isPending ? t("tools.exppattern.submitting") : t("tools.exppattern.submit") }}
          </button>
          <button type="button" class="rounded-md border px-4 py-2" data-testid="exppattern-clear" @click="clear">
            {{ t("common.clear") }}
          </button>
        </div>
      </form>

      <section aria-live="polite" class="grid gap-4" data-testid="exppattern-result">
        <p v-if="isPending" role="status" data-testid="exppattern-loading">{{ t("tools.exppattern.loading") }}</p>
        <div v-else-if="requestError" role="alert" class="grid gap-2 rounded-md border border-red-700 p-4" data-testid="exppattern-error">
          <p>{{ t("tools.exppattern.errorTitle") }}</p>
          <button type="button" class="w-fit underline" @click="submit">{{ t("common.retry") }}</button>
        </div>
        <p v-else-if="!result" class="text-sm opacity-70" data-testid="exppattern-empty">
          {{ t("tools.exppattern.emptyPrompt") }}
        </p>
        <article v-else class="grid gap-4 rounded-lg border p-5" data-testid="exppattern-summary">
          <header class="grid gap-1">
            <h2 class="text-lg font-semibold">{{ t("tools.exppattern.matrixTitle") }}</h2>
            <p class="text-sm opacity-75">
              {{ result.assembly_name }} · {{ result.assembly_version }} ·
              {{ t("tools.exppattern.releaseLabel") }} {{ result.release_id }} ·
              {{ t("tools.exppattern.summaryDesc", { genes: result.genes.length, conditions: result.conditions.length }) }}
            </p>
            <p class="text-xs opacity-70">
              {{ t("tools.exppattern.scaleBadge") }}: {{ scaleLabel(result.scale) }} ·
              {{ t("tools.exppattern.rowOrder") }}: {{ clusteringLabel(result.clustering) }}
            </p>
          </header>

          <div v-if="missingGenes.length" class="rounded-md border p-3 text-sm" data-testid="exppattern-missing">
            <p class="font-medium">{{ t("tools.exppattern.missingCount", { count: missingGenes.length }) }}</p>
            <p class="mt-1 break-words font-mono">{{ missingGenes.join(", ") }}</p>
          </div>
          <p v-if="!hasData" class="text-sm opacity-70" data-testid="exppattern-no-data">
            {{ t("tools.exppattern.noDataDesc") }}
          </p>

          <div v-if="hasData" class="max-h-[65vh] overflow-auto rounded-md border">
            <table class="min-w-full border-collapse text-xs" :aria-label="t('tools.exppattern.matrixAria')">
              <thead class="sticky top-0 z-10 bg-white">
                <tr>
                  <th scope="col" class="sticky left-0 border-b bg-white p-2 text-left">{{ t("tools.exppattern.geneCol") }}</th>
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
    </div>
  </PortalLayout>
</template>
