<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  seqFetchGenes,
  seqFetchRegion,
  type AssemblyInfo,
  type SeqFetchResponse,
} from "@soymutdb/api-client";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { assembliesQueryOptions } from "../lib/query-options";

type Mode = "genes" | "region";

const MAX_GENES = 200;
const MAX_REGION_BP = 1_000_000;
const PREVIEW_MAX_LINES = 120;

const mode = ref<Mode>("genes");
const genesRaw = ref("");
const assembly = ref("");
const chromosome = ref("");
const start = ref("");
const end = ref("");
const fieldErrors = ref<Record<string, string>>({});
const result = ref<SeqFetchResponse | null>(null);

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed(() => toValue(assembliesQuery.data) ?? []);
const isAssembliesLoading = computed(() => toValue(assembliesQuery.isLoading));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));

watch(
  assemblies,
  (items: AssemblyInfo[]) => {
    if (assembly.value) return;
    const defaultAssembly = items.find((item) => item.is_default) ?? items[0];
    if (defaultAssembly) assembly.value = defaultAssembly.name;
  },
  { immediate: true },
);

const fetchMutation = useMutation({
  mutationFn: () => {
    if (mode.value === "genes") {
      return seqFetchGenes(assembly.value, parseGenes(genesRaw.value));
    }
    return seqFetchRegion(
      assembly.value,
      `${chromosome.value.trim()}:${start.value}-${end.value}`,
    );
  },
  onSuccess: (data) => {
    result.value = data;
  },
});

const isFetching = computed(() => toValue(fetchMutation.isPending));
const fetchError = computed(() => toValue(fetchMutation.error));
const missingGenes = computed(() => result.value?.missing ?? []);
const fastaLines = computed(() => result.value?.sequence?.split("\n") ?? []);
const previewIsTruncated = computed(() => fastaLines.value.length > PREVIEW_MAX_LINES);
const visibleFasta = computed(() =>
  previewIsTruncated.value
    ? `${fastaLines.value.slice(0, PREVIEW_MAX_LINES).join("\n")}\n…`
    : fastaLines.value.join("\n"),
);

function parseGenes(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;]+/)
        .map((geneId) => geneId.trim())
        .filter(Boolean),
    ),
  ];
}

function selectMode(nextMode: Mode) {
  mode.value = nextMode;
  fieldErrors.value = {};
  result.value = null;
  fetchMutation.reset();
}

function selectAssembly(event: Event) {
  assembly.value = (event.target as HTMLSelectElement).value;
  result.value = null;
  fieldErrors.value = {};
  fetchMutation.reset();
}

function submit() {
  const errors: Record<string, string> = {};
  if (!assembly.value) errors.assembly = "Choose an assembly.";

  if (mode.value === "genes") {
    const genes = parseGenes(genesRaw.value);
    if (genes.length === 0) errors.genes = "Enter at least one gene accession.";
    else if (genes.length > MAX_GENES) errors.genes = `Enter no more than ${MAX_GENES} unique gene accessions.`;
  } else {
    const parsedStart = Number(start.value);
    const parsedEnd = Number(end.value);
    if (!chromosome.value.trim()) errors.chromosome = "Enter a chromosome name.";
    if (!Number.isInteger(parsedStart) || parsedStart < 1) {
      errors.start = "Start must be a positive whole number.";
    }
    if (!Number.isInteger(parsedEnd) || parsedEnd < parsedStart) {
      errors.end = "End must be a whole number at or after start.";
    } else if (Number.isInteger(parsedStart) && parsedStart > 0 && parsedEnd - parsedStart + 1 > MAX_REGION_BP) {
      errors.end = `A single region may not exceed ${MAX_REGION_BP.toLocaleString()} bp.`;
    }
  }

  fieldErrors.value = errors;
  if (Object.keys(errors).length > 0) return;
  result.value = null;
  fetchMutation.mutate();
}

function retry() {
  fetchMutation.mutate();
}

function clearForm() {
  genesRaw.value = "";
  chromosome.value = "";
  start.value = "";
  end.value = "";
  fieldErrors.value = {};
  result.value = null;
  fetchMutation.reset();
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main class="mx-auto max-w-6xl p-8">
      <p class="text-sm opacity-70">
        <RouterLink to="/tools" class="underline">Research tools</RouterLink>
      </p>
      <h1 class="mt-2 text-2xl font-semibold">Sequence fetch (SeqFetch)</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">
        Extract FASTA sequences from one explicit assembly. Coordinates are 1-based and inclusive.
      </p>

      <div class="mt-6 grid items-start gap-6 lg:grid-cols-[1.2fr_1fr]">
        <form class="grid gap-5 rounded-lg border p-5" @submit.prevent="submit">
          <div>
            <label for="seqfetch-assembly" class="block text-sm font-medium">Assembly</label>
            <select
              id="seqfetch-assembly"
              class="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
              :value="assembly"
              :disabled="isAssembliesLoading || isFetching"
              data-testid="seqfetch-assembly"
              aria-describedby="seqfetch-assembly-help seqfetch-assembly-error"
              :aria-invalid="Boolean(fieldErrors.assembly)"
              @change="selectAssembly"
            >
              <option value="" disabled>Select an assembly</option>
              <option v-for="item in assemblies" :key="item.id" :value="item.name">
                {{ item.name }}{{ item.is_default ? " · default" : "" }}
              </option>
            </select>
            <p id="seqfetch-assembly-help" class="mt-1 text-xs opacity-70">
              Both gene and region requests are limited to this assembly.
            </p>
            <p
              v-if="fieldErrors.assembly"
              id="seqfetch-assembly-error"
              class="mt-1 text-sm text-red-700"
              data-testid="seqfetch-assembly-error"
            >
              {{ fieldErrors.assembly }}
            </p>
            <p v-if="isAssembliesLoading" class="mt-1 text-sm opacity-70">Loading assemblies…</p>
            <p v-else-if="isAssembliesError" class="mt-1 text-sm text-red-700" data-testid="seqfetch-assemblies-error">
              Assemblies could not be loaded. Refresh the page and try again.
            </p>
          </div>

          <div class="flex flex-wrap gap-2" role="tablist" aria-label="Sequence extraction mode">
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'genes'"
              class="rounded-md border px-3 py-2 text-sm"
              data-testid="seqfetch-mode-genes"
              @click="selectMode('genes')"
            >
              Gene list
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'region'"
              class="rounded-md border px-3 py-2 text-sm"
              data-testid="seqfetch-mode-region"
              @click="selectMode('region')"
            >
              Genomic region
            </button>
          </div>

          <div v-if="mode === 'genes'" role="tabpanel" class="grid gap-2">
            <label for="seqfetch-genes" class="text-sm font-medium">Gene accessions</label>
            <textarea
              id="seqfetch-genes"
              v-model="genesRaw"
              rows="7"
              class="w-full rounded-md border bg-background p-3 font-mono text-sm"
              placeholder="Glyma.01G000100, Glyma.02G000200"
              aria-describedby="seqfetch-genes-help seqfetch-genes-error"
              :aria-invalid="Boolean(fieldErrors.genes)"
              data-testid="seqfetch-genes"
            />
            <p id="seqfetch-genes-help" class="text-xs opacity-70">
              Separate accessions with spaces, commas, or semicolons. Up to 200 unique accessions.
            </p>
            <p
              v-if="fieldErrors.genes"
              id="seqfetch-genes-error"
              class="text-sm text-red-700"
              data-testid="seqfetch-genes-error"
            >
              {{ fieldErrors.genes }}
            </p>
          </div>

          <div v-else role="tabpanel" class="grid gap-4">
            <div>
              <label for="seqfetch-chromosome" class="block text-sm font-medium">Chromosome</label>
              <input
                id="seqfetch-chromosome"
                v-model="chromosome"
                class="mt-1 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
                placeholder="Chr01"
                :aria-invalid="Boolean(fieldErrors.chromosome)"
              />
              <p v-if="fieldErrors.chromosome" class="mt-1 text-sm text-red-700">{{ fieldErrors.chromosome }}</p>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="seqfetch-start" class="block text-sm font-medium">Start</label>
                <input
                  id="seqfetch-start"
                  v-model="start"
                  type="number"
                  min="1"
                  class="mt-1 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
                  :aria-invalid="Boolean(fieldErrors.start)"
                  data-testid="seqfetch-start"
                />
                <p v-if="fieldErrors.start" class="mt-1 text-sm text-red-700">{{ fieldErrors.start }}</p>
              </div>
              <div>
                <label for="seqfetch-end" class="block text-sm font-medium">End</label>
                <input
                  id="seqfetch-end"
                  v-model="end"
                  type="number"
                  min="1"
                  class="mt-1 w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
                  :aria-invalid="Boolean(fieldErrors.end)"
                  data-testid="seqfetch-end"
                />
                <p v-if="fieldErrors.end" class="mt-1 text-sm text-red-700">{{ fieldErrors.end }}</p>
              </div>
            </div>
            <p class="text-xs opacity-70">Regions are capped at {{ MAX_REGION_BP.toLocaleString() }} bp per request.</p>
          </div>

          <div class="flex flex-wrap gap-2">
            <button
              type="submit"
              class="rounded-md border px-4 py-2 text-sm font-medium"
              :disabled="isFetching || isAssembliesLoading || !assembly"
              data-testid="seqfetch-submit"
            >
              {{ isFetching ? "Extracting…" : "Extract FASTA" }}
            </button>
            <button
              type="button"
              class="rounded-md border px-4 py-2 text-sm"
              :disabled="isFetching"
              data-testid="seqfetch-clear"
              @click="clearForm"
            >
              Clear
            </button>
          </div>
        </form>

        <section class="min-h-48 rounded-lg border p-5" aria-live="polite" data-testid="seqfetch-result">
          <p v-if="isFetching" class="text-sm opacity-70" data-testid="seqfetch-loading">
            Extracting sequences…
          </p>
          <div v-else-if="fetchError" class="grid gap-3" data-testid="seqfetch-error">
            <p class="font-medium text-red-700">Sequence extraction failed.</p>
            <p class="text-sm opacity-70">{{ fetchError instanceof Error ? fetchError.message : "The request could not be completed." }}</p>
            <button type="button" class="w-fit rounded-md border px-3 py-2 text-sm" @click="retry">
              Retry
            </button>
          </div>
          <div v-else-if="!result" class="text-sm opacity-70" data-testid="seqfetch-empty">
            Choose an assembly and submit a gene list or genomic region to see the FASTA result.
          </div>
          <div v-else class="grid gap-4">
            <div>
              <h2 class="font-medium">FASTA result</h2>
              <p class="mt-1 text-sm opacity-70">
                {{ assembly }} · {{ result.count }} sequence{{ result.count === 1 ? "" : "s" }}
              </p>
              <p v-if="result.truncated" class="mt-1 text-sm opacity-70">
                The full result is available from the temporary download link.
              </p>
            </div>
            <pre
              v-if="result.sequence"
              class="max-h-[420px] overflow-auto rounded-md border bg-black/5 p-3 font-mono text-xs leading-relaxed"
              data-testid="seqfetch-fasta-preview"
            >{{ visibleFasta }}</pre>
            <p v-if="previewIsTruncated" class="text-xs opacity-70">
              Showing the first {{ PREVIEW_MAX_LINES }} lines of the inline result.
            </p>
            <a
              v-if="result.download_url"
              :href="result.download_url"
              download
              rel="noopener noreferrer"
              class="w-fit rounded-md border px-3 py-2 text-sm underline"
              data-testid="seqfetch-download"
            >
              Download FASTA
            </a>
            <div v-if="missingGenes.length > 0" class="rounded-md border border-amber-500/40 p-3">
              <h3 class="text-sm font-medium">Accessions not found in {{ assembly }}</h3>
              <ul class="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
                <li v-for="geneId in missingGenes" :key="geneId">{{ geneId }}</li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </main>
  </ConfigProvider>
</template>
