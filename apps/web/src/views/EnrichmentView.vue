<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  runEnrichment,
  type AssemblyInfo,
  type EnrichmentGseaResponse,
  type EnrichmentResponse,
} from "@soymutdb/api-client";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { assembliesQueryOptions } from "../lib/query-options";

type Mode = "ora" | "gsea";
type Result = EnrichmentResponse | EnrichmentGseaResponse;
interface TermRow {
  id: string;
  name: string;
  pValue: number;
  qValue: number;
  size: number;
  genes: string[];
  es: number | null;
  nes: number | null;
}

const mode = ref<Mode>("ora");
const assemblyId = ref("");
const genesRaw = ref("");
const rankedGenesRaw = ref("");
const ontology = ref<"go" | "kegg">("go");
const pThreshold = ref("0.05");
const minGenes = ref("5");
const fieldError = ref("");
const result = ref<Result | null>(null);

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

const enrichmentMutation = useMutation({
  mutationFn: () => {
    if (mode.value === "gsea") {
      const pairs = parseRankedGenes(rankedGenesRaw.value);
      return runEnrichment({
        assembly_id: Number(assemblyId.value),
        genes: pairs.map((pair) => pair.gene),
        values: pairs.map((pair) => pair.value),
        mode: "gsea",
        ontology: ontology.value,
        p_threshold: Number(pThreshold.value),
        max_terms: 50,
        min_genes: Number(minGenes.value),
      });
    }
    return runEnrichment({
      assembly_id: Number(assemblyId.value),
      genes: parseGenes(genesRaw.value),
      mode: "ora",
      ontology: ontology.value,
      p_threshold: Number(pThreshold.value),
      max_terms: 50,
      min_genes: 5,
    });
  },
  onSuccess: (data) => {
    result.value = data;
  },
});

const isPending = computed(() => toValue(enrichmentMutation.isPending));
const requestError = computed(() => toValue(enrichmentMutation.error));
const rows = computed<TermRow[]>(() =>
  (result.value?.terms ?? []).map((term) => ({
    id: term.id,
    name: term.name,
    pValue: term.p_value,
    qValue: term.q_value,
    size: "size" in term ? term.size : term.gene_count,
    genes: term.genes,
    es: "es" in term ? term.es : null,
    nes: "nes" in term ? term.nes : null,
  })),
);

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

function parseRankedGenes(raw: string): Array<{ gene: string; value: number }> {
  const seen = new Set<string>();
  const pairs: Array<{ gene: string; value: number }> = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [gene, valueText, extra] = trimmed.split(/[\s\t]+/);
    const value = Number(valueText);
    if (!gene || valueText === undefined || extra !== undefined || !Number.isFinite(value)) {
      throw new Error("Enter each ranked gene as: gene ID, then one finite value.");
    }
    if (!seen.has(gene)) {
      seen.add(gene);
      pairs.push({ gene, value });
    }
  }
  return pairs;
}

function selectAssembly(event: Event) {
  assemblyId.value = (event.target as HTMLSelectElement).value;
  result.value = null;
  fieldError.value = "";
  enrichmentMutation.reset();
}

function submit() {
  if (!assemblyId.value) {
    fieldError.value = "Select an assembly.";
    return;
  }
  const p = Number(pThreshold.value);
  if (!Number.isFinite(p) || p <= 0 || p > 1) {
    fieldError.value = "Enter a p-value threshold greater than 0 and at most 1.";
    return;
  }
  if (mode.value === "ora") {
    const genes = parseGenes(genesRaw.value);
    if (!genes.length || genes.length > 500) {
      fieldError.value = "Enter between 1 and 500 unique gene IDs.";
      return;
    }
  } else {
    let pairs: Array<{ gene: string; value: number }>;
    try {
      pairs = parseRankedGenes(rankedGenesRaw.value);
    } catch (error) {
      fieldError.value = error instanceof Error ? error.message : "Invalid ranked gene list.";
      return;
    }
    if (!pairs.length || pairs.length > 500) {
      fieldError.value = "Enter between 1 and 500 ranked genes.";
      return;
    }
    const minimum = Number(minGenes.value);
    if (!Number.isInteger(minimum) || minimum < 1 || minimum > 500) {
      fieldError.value = "Minimum term size must be an integer from 1 to 500.";
      return;
    }
  }
  fieldError.value = "";
  result.value = null;
  enrichmentMutation.mutate();
}

function changeMode(next: Mode) {
  mode.value = next;
  fieldError.value = "";
  result.value = null;
  enrichmentMutation.reset();
}

function clear() {
  genesRaw.value = "";
  rankedGenesRaw.value = "";
  ontology.value = "go";
  pThreshold.value = "0.05";
  minGenes.value = "5";
  fieldError.value = "";
  result.value = null;
  enrichmentMutation.reset();
}

function formatP(value: number): string {
  return value === 0 ? "0" : value < 0.001 ? value.toExponential(2) : value.toFixed(4);
}

function barWidth(qValue: number): string {
  const magnitude = qValue <= 0 ? 10 : Math.min(10, -Math.log10(qValue));
  return `${Math.max(3, (magnitude / 10) * 100)}%`;
}

function formatLogQ(qValue: number): string {
  const magnitude = qValue <= 0 ? 10 : Math.min(10, -Math.log10(qValue));
  return magnitude.toFixed(2);
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main class="mx-auto grid max-w-7xl gap-8 p-6 md:p-8" data-testid="enrichment-page">
      <header class="grid gap-2">
        <RouterLink to="/tools" class="text-sm underline opacity-70">Research tools</RouterLink>
        <h1 class="text-2xl font-semibold">GO / KEGG enrichment</h1>
        <p class="max-w-3xl text-sm opacity-75">
          Run over-representation or ranked gene-set analysis against annotations from one selected assembly.
        </p>
      </header>

      <form class="grid gap-5 rounded-lg border p-5" @submit.prevent="submit">
        <div class="grid gap-2">
          <label for="enrichment-assembly" class="text-sm font-medium">Assembly</label>
          <select
            id="enrichment-assembly"
            class="rounded-md border bg-transparent p-2"
            :value="assemblyId"
            :disabled="isAssembliesLoading || isAssembliesError"
            data-testid="enrichment-assembly"
            @change="selectAssembly"
          >
            <option value="" disabled>Select an assembly</option>
            <option v-for="item in assemblies" :key="item.id" :value="item.id">
              {{ item.name }} · {{ item.version }}{{ item.is_default ? " (default)" : "" }}
            </option>
          </select>
          <p v-if="isAssembliesLoading" role="status" class="text-sm opacity-70">Loading assemblies…</p>
          <p v-else-if="isAssembliesError" role="alert" class="text-sm text-red-700">Assemblies could not be loaded.</p>
          <p v-else class="text-xs opacity-70">Input genes, annotation terms, and the background set use this assembly.</p>
        </div>

        <div class="flex flex-wrap gap-2" role="group" aria-label="Analysis mode">
          <button type="button" :aria-pressed="mode === 'ora'" class="rounded-md border px-3 py-2" data-testid="enrichment-mode-ora" @click="changeMode('ora')">
            Over-representation
          </button>
          <button type="button" :aria-pressed="mode === 'gsea'" class="rounded-md border px-3 py-2" data-testid="enrichment-mode-gsea" @click="changeMode('gsea')">
            Ranked GSEA
          </button>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <label class="grid gap-2 text-sm">
            <span>Ontology</span>
            <select v-model="ontology" class="rounded-md border bg-transparent p-2" data-testid="enrichment-ontology">
              <option value="go">GO</option>
              <option value="kegg">KEGG</option>
            </select>
          </label>
          <label class="grid gap-2 text-sm">
            <span>Raw p-value threshold</span>
            <input v-model="pThreshold" type="number" min="0.000001" max="1" step="any" class="rounded-md border bg-transparent p-2" data-testid="enrichment-p-threshold" />
          </label>
        </div>

        <div v-if="mode === 'ora'" class="grid gap-2">
          <label for="enrichment-genes" class="text-sm font-medium">Gene IDs</label>
          <textarea id="enrichment-genes" v-model="genesRaw" rows="7" class="rounded-md border bg-transparent p-3 font-mono text-sm" placeholder="One gene ID per line" data-testid="enrichment-genes" />
          <p class="text-xs opacity-70">Up to 500 unique gene IDs.</p>
        </div>
        <div v-else class="grid gap-3">
          <label for="enrichment-ranked-genes" class="text-sm font-medium">Ranked gene values</label>
          <textarea id="enrichment-ranked-genes" v-model="rankedGenesRaw" rows="7" class="rounded-md border bg-transparent p-3 font-mono text-sm" placeholder="Gene ID<TAB>log2 fold-change" data-testid="enrichment-ranked-genes" />
          <label class="grid max-w-xs gap-2 text-sm">
            <span>Minimum term size</span>
            <input v-model="minGenes" type="number" min="1" max="500" step="1" class="rounded-md border bg-transparent p-2" data-testid="enrichment-min-genes" />
          </label>
        </div>

        <p v-if="fieldError" role="alert" class="text-sm text-red-700" data-testid="enrichment-field-error">{{ fieldError }}</p>
        <div class="flex flex-wrap gap-3">
          <button type="submit" class="rounded-md border px-4 py-2 font-medium disabled:opacity-50" :disabled="isPending || isAssembliesLoading || isAssembliesError" data-testid="enrichment-submit">
            {{ isPending ? "Analyzing…" : "Run enrichment" }}
          </button>
          <button type="button" class="rounded-md border px-4 py-2" data-testid="enrichment-clear" @click="clear">Clear</button>
        </div>
      </form>

      <section aria-live="polite" class="grid gap-4" data-testid="enrichment-result">
        <p v-if="isPending" role="status">Running analysis…</p>
        <div v-else-if="requestError" role="alert" class="rounded-md border border-red-700 p-4" data-testid="enrichment-error">
          <p>Analysis is unavailable.</p>
          <p class="mt-2 text-sm">{{ requestError.message }}</p>
        </div>
        <p v-else-if="!result" class="text-sm opacity-70">Submit a gene list to run an analysis.</p>
        <article v-else class="grid gap-4 rounded-lg border p-5" data-testid="enrichment-summary">
          <header class="grid gap-1">
            <h2 class="text-lg font-semibold">{{ result.mode === "gsea" ? "GSEA results" : "ORA results" }}</h2>
            <p class="text-sm opacity-75">
              {{ result.assembly_name }} · {{ result.assembly_version }} · release {{ result.release_id }} ·
              {{ result.input_genes }} input genes / {{ result.background_genes }} annotated background genes
            </p>
            <p class="text-xs opacity-70">{{ result.ontology.toUpperCase() }} · {{ rows.length }} terms</p>
            <p v-if="result.annotation_source" class="break-words text-xs opacity-70" data-testid="enrichment-provenance">
              Source:
              <a :href="result.annotation_source.url" target="_blank" rel="noopener noreferrer" class="underline">
                {{ result.annotation_source.name }} · {{ result.annotation_source.version }}
              </a>
              · SHA-256 <code>{{ result.annotation_source.sha256 }}</code>
            </p>
            <p v-else class="text-xs opacity-70" data-testid="enrichment-provenance-empty">
              No annotation source is loaded for this release.
            </p>
          </header>
          <p v-if="result.message" class="rounded-md border p-3 text-sm" data-testid="enrichment-message">{{ result.message }}</p>
          <p v-if="!rows.length && !result.message" class="text-sm opacity-70">No terms passed the selected threshold.</p>
          <div v-if="rows.length" class="grid gap-4">
            <ul aria-label="Enrichment significance plot" class="grid gap-2 rounded-md border p-3 text-sm" data-testid="enrichment-plot">
              <li v-for="row in rows" :key="row.id" class="grid gap-1">
                <div class="flex justify-between gap-3"><span class="truncate">{{ row.name }} <code>{{ row.id }}</code></span><span>-log10(q) {{ formatLogQ(row.qValue) }}</span></div>
                <div class="h-2 rounded bg-slate-100"><div class="h-2 rounded bg-blue-600" :style="{ width: barWidth(row.qValue) }" /></div>
              </li>
            </ul>
            <div class="overflow-auto rounded-md border">
              <table class="min-w-full text-sm" aria-label="Enrichment terms">
                <thead><tr><th scope="col" class="p-2 text-left">Term</th><th scope="col" class="p-2 text-right">p</th><th scope="col" class="p-2 text-right">q</th><th scope="col" class="p-2 text-right">Genes</th><th v-if="result.mode === 'gsea'" scope="col" class="p-2 text-right">ES / NES</th></tr></thead>
                <tbody>
                  <tr v-for="row in rows" :key="row.id" class="border-t align-top">
                    <th scope="row" class="p-2 text-left"><code>{{ row.id }}</code><span class="ml-2 font-normal">{{ row.name }}</span><p class="mt-1 max-w-lg break-words font-mono text-xs opacity-70">{{ row.genes.join(", ") }}</p></th>
                    <td class="p-2 text-right font-mono">{{ formatP(row.pValue) }}</td>
                    <td class="p-2 text-right font-mono">{{ formatP(row.qValue) }}</td>
                    <td class="p-2 text-right font-mono">{{ row.size }}</td>
                    <td v-if="result.mode === 'gsea'" class="p-2 text-right font-mono">{{ row.es?.toFixed(3) }} / {{ row.nes?.toFixed(3) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </article>
      </section>
    </main>
  </ConfigProvider>
</template>
