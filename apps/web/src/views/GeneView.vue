<script setup lang="ts">
import { useInfiniteQuery, useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { normalizeInterval, length as intervalLength } from "@soymutdb/genome-view-model";
import { Button, Tag } from "@soymutdb/ui-vue";

import GeneModelPreview from "../components/GeneModelPreview.vue";
import PortalLayout from "../components/PortalLayout.vue";
import AppIcon from "../components/table/AppIcon.vue";
import DataTable from "../components/table/DataTable.vue";
import PageHeader from "../components/table/PageHeader.vue";
import type { TableColumn } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import { isJbrowseEnabled, resolveJbrowseBaseUrl } from "../lib/deployment";
import { t } from "../lib/i18n";
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
  // Core-only deployments run no genome browser: no link into a dead upstream.
  if (!isJbrowseEnabled()) return undefined;
  const g = gene.value;
  if (!g) return undefined;
  const params = new URLSearchParams({ loc: `${g.chromosome}:${g.start_pos}..${g.end_pos}` });
  if (g.assembly_id) params.set("assembly", String(g.assembly_id));
  // Canonical origin name shared with the api-client / pipeline
  // (VITE_JBROWSE_BASE_URL), never a localhost fallback.
  const base = resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_BASE_URL);
  return `${base}?${params.toString()}`;
});

const transcriptColumns: TableColumn[] = [
  { id: "name", header: t("genes.transcriptName"), primary: true, cellClass: "font-mono" },
  { id: "biotype", header: t("genes.biotypeLabel") },
  { id: "location", header: t("genes.transcriptLocation"), cellClass: "font-mono" },
  { id: "exons", header: t("genes.exonsLabel"), numeric: true, align: "right" },
];

const expressionColumns: TableColumn[] = [
  { id: "library_name", header: t("genes.libraryLabel"), primary: true },
  { id: "tissue", header: t("genes.tissueLabel") },
  { id: "treatment", header: t("genes.treatmentLabel") },
  { id: "fpkm", header: t("genes.fpkmLabel"), numeric: true, align: "right" },
  { id: "tpm", header: t("genes.tpmLabel"), numeric: true, align: "right" },
];

const homologColumns: TableColumn[] = [
  { id: "species", header: t("genes.speciesLabel"), primary: true },
  { id: "gene_id", header: t("genes.homologGeneLabel"), cellClass: "font-mono" },
  { id: "type", header: t("genes.relationshipLabel") },
  { id: "source", header: t("genes.sourceLabel") },
];

function fixed(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}
</script>

<template>
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <RouterLink
        to="/search"
        class="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <AppIcon name="arrow-left" class="size-4" />
        {{ t("genes.backToSearch") }}
      </RouterLink>

      <StateBlock
        v-if="isLoading"
        data-testid="gene-loading"
        variant="loading"
        :title="t('common.loading')"
        :rows="6"
        class="mt-6"
      />
      <StateBlock
        v-else-if="isError"
        data-testid="gene-error"
        variant="error"
        :title="t('genes.loadError')"
        class="mt-6"
      />

      <article v-else-if="gene" data-testid="gene-detail" class="mt-6">
        <PageHeader>
          <template #badges>
            <Tag class="m-0 font-mono text-[10px] uppercase">{{ gene.biotype }}</Tag>
            <Tag class="m-0 font-mono text-[10px]">{{ gene.chromosome }}</Tag>
          </template>
          <template #title>
            <span class="font-mono" data-testid="gene-id">{{ gene.gene_id }}</span>
          </template>
          <template #actions>
            <a
              v-if="jbrowseHref"
              :href="jbrowseHref"
              data-testid="gene-jbrowse"
              class="inline-flex min-h-10 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium transition-colors hover:bg-accent"
            >
              <AppIcon name="microscope" class="size-4" />
              {{ t("genes.viewInBrowser") }}
            </a>
          </template>
        </PageHeader>

        <p v-if="gene.symbol || gene.description" class="mt-3 max-w-2xl text-muted-foreground">
          <span v-if="gene.symbol" class="font-display text-lg">{{ gene.symbol }}</span>
          <span v-if="gene.symbol && gene.description"> · </span>
          <span v-if="gene.description">{{ gene.description }}</span>
        </p>

        <dl class="mt-6 grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2">
          <div class="bg-card px-4 py-3">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">
              {{ t("genes.assemblyLabel") }}
            </dt>
            <dd class="mt-1 text-sm" data-testid="gene-assembly">
              {{ gene.assembly_name ?? "—" }}
              <span v-if="gene.assembly_id" class="font-mono text-muted-foreground">(#{{ gene.assembly_id }})</span>
            </dd>
          </div>
          <div class="bg-card px-4 py-3">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">
              {{ t("genes.coordinatesLabel") }}
            </dt>
            <dd class="mt-1 font-mono text-sm" data-testid="gene-coords">
              {{ gene.chromosome }}:{{ gene.start_pos }}..{{ gene.end_pos }}
              <template v-if="interval">
                {{ t("genes.coordinatesDetail", { length: interval.length, strand: gene.strand }) }}
              </template>
            </dd>
          </div>
          <div v-if="gene.variant_count !== undefined" class="bg-card px-4 py-3">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">
              {{ t("genes.variantsLabel") }}
            </dt>
            <dd class="mt-1 font-mono text-sm tabular-nums" data-testid="gene-variants">
              {{ gene.variant_count }}
              <span v-if="gene.high_impact_variants" class="text-muted-foreground">
                · {{ t("genes.highImpactCount", { count: gene.high_impact_variants }) }}
              </span>
            </dd>
          </div>
          <div class="bg-card px-4 py-3">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">
              {{ t("genes.detail") }}
            </dt>
            <dd class="mt-1 font-mono text-sm">{{ gene.source ?? "—" }}</dd>
          </div>
        </dl>

        <div class="mt-6 rounded-xl border bg-card p-4 shadow-sm">
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
        </div>

        <section
          v-if="gene.transcripts.length > 0"
          class="mt-8"
          aria-labelledby="gene-transcripts"
          data-testid="gene-transcripts"
        >
          <h2 id="gene-transcripts" class="font-display text-2xl font-semibold">
            {{ t("genes.transcripts") }}
          </h2>
          <div class="mt-4">
            <DataTable
              :columns="transcriptColumns"
              :rows="gene.transcripts"
              :row-key="(row) => String(row.id)"
              :row-attrs="() => ({ 'data-testid': 'transcript-row' })"
              :aria-label="t('genes.transcripts')"
            >
              <template #cell-name="{ row }">
                <span>{{ row.name ?? row.id }}</span>
                <span v-if="row.is_canonical" class="ml-1 text-muted-foreground">
                  · {{ t("genes.canonicalBadge") }}
                </span>
              </template>
              <template #cell-biotype="{ row }">{{ row.biotype ?? "—" }}</template>
              <template #cell-location="{ row }">
                {{ row.start }}..{{ row.end }} ({{ row.strand }})
              </template>
              <template #cell-exons="{ row }">{{ row.exons.length }}</template>
            </DataTable>
          </div>
        </section>

        <section
          v-if="gene.assembly_id"
          class="mt-8"
          aria-labelledby="gene-expression-heading"
          data-testid="gene-expression"
        >
          <h2 id="gene-expression-heading" class="font-display text-2xl font-semibold">
            {{ t("genes.tabs.expression") }}
          </h2>
          <p class="mt-1 text-sm text-muted-foreground">{{ t("genes.expressionNote") }}</p>
          <StateBlock
            v-if="toValue(expressionQuery.isLoading)"
            data-testid="expression-loading"
            variant="loading"
            :title="t('genes.expressionLoading')"
            :rows="3"
            class="mt-4"
          />
          <StateBlock
            v-else-if="toValue(expressionQuery.isError) && expressionRecords.length === 0"
            data-testid="expression-error"
            variant="error"
            :title="t('genes.expressionError')"
            class="mt-4"
          />
          <StateBlock
            v-else-if="expressionRecords.length === 0"
            data-testid="expression-empty"
            variant="empty"
            icon="file-text"
            :title="t('genes.expressionEmpty')"
            class="mt-4"
          />
          <template v-else>
            <p
              v-if="toValue(expressionQuery.isError)"
              class="mt-3 text-sm text-destructive"
              data-testid="expression-more-error"
            >
              {{ t("genes.expressionMoreError") }}
            </p>
            <div class="mt-4">
              <DataTable
                :columns="expressionColumns"
                :rows="expressionRecords"
                :row-key="(row, index) => `${row.library_id}:${index}`"
                :row-attrs="() => ({ 'data-testid': 'expression-row' })"
                :aria-label="t('genes.expressionAria')"
              >
                <template #cell-fpkm="{ row }">{{ fixed(row.fpkm) }}</template>
                <template #cell-tpm="{ row }">{{ fixed(row.tpm) }}</template>
              </DataTable>
            </div>
            <Button
              v-if="toValue(expressionQuery.hasNextPage)"
              class="mt-4"
              data-testid="expression-load-more"
              :disabled="toValue(expressionQuery.isFetchingNextPage)"
              @click="expressionQuery.fetchNextPage()"
            >
              <AppIcon name="arrow-down" class="mr-1.5 inline size-3.5" />
              {{
                toValue(expressionQuery.isFetchingNextPage)
                  ? t("common.loading")
                  : t("genes.loadMoreExpression")
              }}
            </Button>
          </template>
        </section>

        <section
          v-if="gene.assembly_id"
          class="mt-8"
          aria-labelledby="gene-homologs-heading"
          data-testid="gene-homologs"
        >
          <h2 id="gene-homologs-heading" class="font-display text-2xl font-semibold">
            {{ t("genes.tabs.homologs") }}
          </h2>
          <StateBlock
            v-if="toValue(homologsQuery.isLoading)"
            data-testid="homologs-loading"
            variant="loading"
            :title="t('genes.homologsLoading')"
            :rows="3"
            class="mt-4"
          />
          <StateBlock
            v-else-if="toValue(homologsQuery.isError) && homologRecords.length === 0"
            data-testid="homologs-error"
            variant="error"
            :title="t('genes.homologsError')"
            class="mt-4"
          />
          <StateBlock
            v-else-if="homologRecords.length === 0"
            data-testid="homologs-empty"
            variant="empty"
            icon="dna"
            :title="t('genes.homologsEmpty')"
            class="mt-4"
          />
          <template v-else>
            <p
              v-if="toValue(homologsQuery.isError)"
              class="mt-3 text-sm text-destructive"
              data-testid="homologs-more-error"
            >
              {{ t("genes.homologsMoreError") }}
            </p>
            <div class="mt-4">
              <DataTable
                :columns="homologColumns"
                :rows="homologRecords"
                :row-key="(row, index) => `${row.species}:${row.gene_id}:${index}`"
                :row-attrs="() => ({ 'data-testid': 'homolog-row' })"
                :aria-label="t('genes.homologsAria')"
              />
            </div>
            <Button
              v-if="toValue(homologsQuery.hasNextPage)"
              class="mt-4"
              data-testid="homologs-load-more"
              :disabled="toValue(homologsQuery.isFetchingNextPage)"
              @click="homologsQuery.fetchNextPage()"
            >
              <AppIcon name="arrow-down" class="mr-1.5 inline size-3.5" />
              {{
                toValue(homologsQuery.isFetchingNextPage)
                  ? t("common.loading")
                  : t("genes.loadMoreHomologs")
              }}
            </Button>
          </template>
        </section>
        <p v-else class="mt-8 text-sm text-muted-foreground" data-testid="gene-associated-data-unavailable">
          {{ t("genes.assemblyHint") }}
        </p>

        <!-- The public detail never renders a private internal identifier. -->
      </article>

      <StateBlock
        v-else
        data-testid="gene-empty"
        variant="empty"
        icon="dna"
        :title="t('genes.notFound')"
        class="mt-6"
      />
    </div>
  </PortalLayout>
</template>
