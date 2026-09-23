<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { normalizeInterval, length as intervalLength } from "@soymutdb/genome-view-model";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { resolveJbrowseBaseUrl } from "../lib/deployment";
import { geneQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

// Gene detail (Phase F). Surfaces the assembly-scoped genomic-coordinate
// contract (DB-CORE-3/4/7): the accession carried under an explicit assembly,
// chromosome + 1-based inclusive coordinates + strand via the neutral
// genome-view-model, variant counts, and a JBrowse deep link bound to the same
// assembly context. Transcript/homolog/expression sub-sections are follow-up
// commits; this slice proves the detail contract + the shared view-model.
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

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const gene = computed(() => toValue(query.data));

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
