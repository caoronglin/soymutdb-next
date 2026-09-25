<script setup lang="ts">
import { useInfiniteQuery, useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { normalizeInterval, length as intervalLength } from "@soymutdb/genome-view-model";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import GeneModelPreview from "../components/GeneModelPreview.vue";
import { resolveJbrowseBaseUrl } from "../lib/deployment";
import {
  geneExpressionQueryOptions,
  geneHomologsQueryOptions,
  geneQueryOptions,
} from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

// Gene detail (Phase F). Surfaces the assembly-scoped genomic-coordinate
// contract (DB-CORE-3/4/7): the accession carried under an explicit assembly,
// chromosome + 1-based inclusive coordinates + strand via the neutral
// genome-view-model, variant counts, merged transcript/exon structure,
// paginated expression/homolog observations, and a JBrowse deep link bound to
// the same assembly context.
const route = useRoute();
const site = useSiteContextStore();
const geneId = computed(() => String(route.params.geneId));
const assembly = computed(() =>
  route.query.assembly ? String(route.query.assembly) : undefined,
);

const query = useQuery(
  computed(() =>
    geneQueryOptions({
      geneId: geneId.value,
      assemblyId: assembly.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);
const gene = computed(() => toValue(query.data));

const expressionQuery = useInfiniteQuery(
  computed(() =>
    geneExpressionQueryOptions({
      geneId: geneId.value,
      assemblyId: gene.value?.assembly_id ? String(gene.value.assembly_id) : undefined,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
      enabled: Boolean(gene.value?.assembly_id),
    }),
  ),
);

const homologsQuery = useInfiniteQuery(
  computed(() =>
    geneHomologsQueryOptions({
      geneId: geneId.value,
      assemblyId: gene.value?.assembly_id ? String(gene.value.assembly_id) : undefined,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
      enabled: Boolean(gene.value?.assembly_id),
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const expressionRecords = computed(() =>
  toValue(expressionQuery.data)?.pages.flatMap((page) => page.expressions) ?? [],
);
const homologRecords = computed(() =>
  toValue(homologsQuery.data)?.pages.flatMap((page) => page.homologs) ?? [],
);

const interval = computed(() => {
  const g = gene.value;
  if (!g || !g.assembly_id) return null;
  try {
    const norm = normalizeInterval({
      assemblyKey: String(g.assembly_id),
      start: g.start_pos,
      end: g.end_pos,
    });
    return { ...norm, length: intervalLength(norm) };
  } catch {
    return null;
  }
});

const jbrowseHref = computed(() => {
  const g = gene.value;
  if (!g) return undefined;
  const params = new URLSearchParams({ loc: `${g.chromosome}:${g.start_pos}..${g.end_pos}` });
  if (g.assembly_id) params.set("assembly", String(g.assembly_id));
  // Canonical origin name shared with the api-client / pipeline
  // (VITE_JBROWSE_BASE_URL), never a localhost fallback.
  const base = resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_BASE_URL);
  return `${base}?${params.toString()}`;
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/search" class="underline">Search</RouterLink></p>

      <div v-if="isLoading" data-testid="gene-loading" class="mt-6 h-24 animate-pulse rounded bg-black/5" />

      <div v-else-if="isError" data-testid="gene-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">Could not load this gene.</p>
      </div>

      <article v-else-if="gene" data-testid="gene-detail" class="mt-4">
        <div class="flex items-center gap-2">
          <Tag class="font-mono uppercase">gene</Tag>
          <h1 class="text-2xl font-semibold" data-testid="gene-id">{{ gene.gene_id }}</h1>
        </div>
        <p class="mt-1 text-sm opacity-70">
          {{ gene.name ?? gene.symbol ?? "—" }} · {{ gene.biotype }}
        </p>

        <dl class="mt-4 grid grid-cols-2 gap-2 text-sm" data-testid="gene-context">
          <dt class="opacity-70">Assembly</dt>
          <dd data-testid="gene-assembly">
            {{ gene.assembly_name ?? "—" }}
            <span v-if="gene.assembly_id" class="font-mono opacity-60">(#{{ gene.assembly_id }})</span>
          </dd>
          <dt class="opacity-70">Coordinates</dt>
          <dd data-testid="gene-coords">
            {{ gene.chromosome }}:{{ gene.start_pos }}..{{ gene.end_pos }}
            <template v-if="interval"> ({{ interval.length }} bp, {{ gene.strand }} strand)</template>
          </dd>
        </dl>

        <section v-if="gene.variant_count !== undefined" class="mt-4 text-sm" data-testid="gene-variants">
          <span class="opacity-70">Variants:</span>
          {{ gene.variant_count }}
          <span v-if="gene.high_impact_variants" class="opacity-70">
            · {{ gene.high_impact_variants }} high-impact
          </span>
        </section>

        <p v-if="gene.description" class="mt-4 text-sm">{{ gene.description }}</p>

        <GeneModelPreview
          v-if="gene.assembly_id"
          :gene-id="gene.gene_id"
          :assembly-id="gene.assembly_id"
          :assembly-name="gene.assembly_name"
          :chromosome="gene.chromosome"
          :start="gene.start_pos"
          :end="gene.end_pos"
          :strand="gene.strand"
          :transcripts="gene.transcripts"
        />

        <section
          v-if="gene.transcripts.length > 0"
          class="mt-6"
          aria-labelledby="gene-transcripts"
          data-testid="gene-transcripts"
        >
          <h2 id="gene-transcripts" class="text-lg font-medium">Transcripts</h2>
          <table class="mt-2 w-full text-sm">
            <thead class="text-left opacity-60">
              <tr>
                <th>Name</th>
                <th>Biotype</th>
                <th>Location</th>
                <th>Exons</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="transcript in gene.transcripts"
                :key="transcript.id"
                data-testid="transcript-row"
              >
                <td>
                  <span class="font-mono">{{ transcript.name ?? transcript.id }}</span>
                  <span v-if="transcript.is_canonical" class="ml-1 opacity-60">· canonical</span>
                </td>
                <td>{{ transcript.biotype ?? "—" }}</td>
                <td class="font-mono">
                  {{ transcript.start }}..{{ transcript.end }} ({{ transcript.strand }})
                </td>
                <td>{{ transcript.exons.length }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section
          v-if="gene.assembly_id"
          class="mt-6"
          aria-labelledby="gene-expression-heading"
          data-testid="gene-expression"
        >
          <h2 id="gene-expression-heading" class="text-lg font-medium">Expression</h2>
          <p class="mt-1 text-sm opacity-70">
            Expression measurements are observations; they do not establish causality.
          </p>
          <p v-if="toValue(expressionQuery.isLoading)" class="mt-3 text-sm" data-testid="expression-loading">
            Loading expression records…
          </p>
          <p
            v-else-if="toValue(expressionQuery.isError) && expressionRecords.length === 0"
            class="mt-3 text-sm text-red-700"
            data-testid="expression-error"
          >
            Expression records could not be loaded.
          </p>
          <p
            v-else-if="expressionRecords.length === 0"
            class="mt-3 text-sm opacity-70"
            data-testid="expression-empty"
          >
            No expression records are available for this gene and assembly.
          </p>
          <template v-else>
            <p
              v-if="toValue(expressionQuery.isError)"
              class="mt-3 text-sm text-red-700"
              data-testid="expression-more-error"
            >
              More expression records could not be loaded. Your loaded records are still shown.
            </p>
            <div class="mt-3 overflow-x-auto">
              <table class="w-full text-sm" aria-label="Gene expression measurements">
                <thead class="text-left opacity-60">
                  <tr>
                    <th>Library</th>
                    <th>Tissue</th>
                    <th>Treatment</th>
                    <th class="text-right">FPKM</th>
                    <th class="text-right">TPM</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(record, index) in expressionRecords"
                    :key="`${record.library_id}:${index}`"
                    data-testid="expression-row"
                  >
                    <td>{{ record.library_name }}</td>
                    <td>{{ record.tissue }}</td>
                    <td>{{ record.treatment }}</td>
                    <td class="text-right tabular-nums">{{ record.fpkm?.toFixed(2) ?? "—" }}</td>
                    <td class="text-right tabular-nums">{{ record.tpm?.toFixed(2) ?? "—" }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button
              v-if="toValue(expressionQuery.hasNextPage)"
              type="button"
              class="mt-3 rounded-md border px-3 py-2 text-sm"
              data-testid="expression-load-more"
              :disabled="toValue(expressionQuery.isFetchingNextPage)"
              @click="expressionQuery.fetchNextPage()"
            >
              {{ toValue(expressionQuery.isFetchingNextPage) ? "Loading…" : "Load more expression data" }}
            </button>
          </template>
        </section>

        <section
          v-if="gene.assembly_id"
          class="mt-6"
          aria-labelledby="gene-homologs-heading"
          data-testid="gene-homologs"
        >
          <h2 id="gene-homologs-heading" class="text-lg font-medium">Homologs</h2>
          <p v-if="toValue(homologsQuery.isLoading)" class="mt-3 text-sm" data-testid="homologs-loading">
            Loading homologs…
          </p>
          <p
            v-else-if="toValue(homologsQuery.isError) && homologRecords.length === 0"
            class="mt-3 text-sm text-red-700"
            data-testid="homologs-error"
          >
            Homologs could not be loaded.
          </p>
          <p
            v-else-if="homologRecords.length === 0"
            class="mt-3 text-sm opacity-70"
            data-testid="homologs-empty"
          >
            No homolog records are available for this gene and assembly.
          </p>
          <template v-else>
            <p
              v-if="toValue(homologsQuery.isError)"
              class="mt-3 text-sm text-red-700"
              data-testid="homologs-more-error"
            >
              More homologs could not be loaded. Your loaded records are still shown.
            </p>
            <div class="mt-3 overflow-x-auto">
              <table class="w-full text-sm" aria-label="Gene homologs">
                <thead class="text-left opacity-60">
                  <tr>
                    <th>Species</th>
                    <th>Homolog gene</th>
                    <th>Relationship</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(homolog, index) in homologRecords"
                    :key="`${homolog.species}:${homolog.gene_id}:${index}`"
                    data-testid="homolog-row"
                  >
                    <td>{{ homolog.species }}</td>
                    <td class="font-mono">{{ homolog.gene_id }}</td>
                    <td>{{ homolog.type }}</td>
                    <td>{{ homolog.source }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button
              v-if="toValue(homologsQuery.hasNextPage)"
              type="button"
              class="mt-3 rounded-md border px-3 py-2 text-sm"
              data-testid="homologs-load-more"
              :disabled="toValue(homologsQuery.isFetchingNextPage)"
              @click="homologsQuery.fetchNextPage()"
            >
              {{ toValue(homologsQuery.isFetchingNextPage) ? "Loading…" : "Load more homologs" }}
            </button>
          </template>
        </section>
        <p v-else class="mt-6 text-sm opacity-70" data-testid="gene-associated-data-unavailable">
          Select an assembly to view expression and homolog records.
        </p>

        <a
          v-if="jbrowseHref"
          :href="jbrowseHref"
          data-testid="gene-jbrowse"
          class="mt-6 inline-block rounded-md border px-3 py-2 text-sm"
        >
          Open in JBrowse 2
        </a>

        <!-- The public detail never renders a private internal identifier. -->
      </article>

      <div v-else data-testid="gene-empty" class="mt-6 text-sm opacity-70">Gene not found.</div>
    </div>
  </ConfigProvider>
</template>
