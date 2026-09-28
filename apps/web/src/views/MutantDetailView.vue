<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import type { PhenotypeResponse } from "@soymutdb/api-client";
import { Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import AppIcon from "../components/table/AppIcon.vue";
import DataTable from "../components/table/DataTable.vue";
import PageHeader from "../components/table/PageHeader.vue";
import type { TableColumn } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import {
  mutantLinePhenotypesQueryOptions,
  mutantLineQueryOptions,
} from "../lib/query-options";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

// Public mutant detail (Phase F, DB-CORE-2). The record is addressed + rendered
// by its public_id ONLY; the private internal persistence key is never sent to
// or rendered on the external site (the API response omits it, and the view
// never accepts or displays an internal id). is_public/unreleased handling is
// server-side.
const route = useRoute();
const site = useSiteContextStore();
const publicId = computed(() => String(route.params.publicId));

const query = useQuery(
  computed(() =>
    mutantLineQueryOptions({
      publicId: publicId.value,
      // The api-client sends the pinned release as X-SoyMutDB-Release, so the
      // cache key must carry the same release (never a hard-coded null).
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const line = computed(() => toValue(query.data));

// Observations are read under the same release/site context as the line; the
// query waits for the detail so an unknown public id does not fire a second
// request whose only possible answer is 404 (mirrors the React route).
const phenotypesQuery = useQuery(
  computed(() =>
    mutantLinePhenotypesQueryOptions({
      publicId: publicId.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
      enabled: Boolean(line.value),
    }),
  ),
);
const phenotypesLoading = computed(() => toValue(phenotypesQuery.isLoading));
const phenotypesError = computed(() => toValue(phenotypesQuery.isError));
const phenotypes = computed<PhenotypeResponse[]>(() => toValue(phenotypesQuery.data) ?? []);

function displayValue(value: string | null): string {
  return value?.trim() ? value : "—";
}

const phenotypeColumns: TableColumn[] = [
  { id: "trait_category", header: t("mutantLines.categoryLabel"), primary: true },
  { id: "trait_name", header: t("genes.transcriptName") },
  { id: "trait_value", header: t("mutantLines.valueLabel") },
  { id: "unit", header: t("common.unit") },
  { id: "description", header: t("mutantLines.description") },
];
</script>

<template>
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <RouterLink
        to="/mutants"
        class="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <AppIcon name="arrow-left" class="size-4" />
        {{ t("mutantLines.title") }}
      </RouterLink>

      <StateBlock
        v-if="isLoading"
        data-testid="mutant-loading"
        variant="loading"
        :title="t('common.loading')"
        :rows="6"
        class="mt-6"
      />
      <StateBlock
        v-else-if="isError"
        data-testid="mutant-error"
        variant="error"
        :title="t('mutantLines.unavailable')"
        class="mt-6"
      />

      <article v-else-if="line" data-testid="mutant-detail" class="mt-6">
        <PageHeader :eyebrow="t('nav.mutantLines')">
          <template #badges>
            <Tag class="font-mono text-[10px] uppercase">{{ t("mutantLines.entityTag") }}</Tag>
            <span
              class="font-mono text-sm text-muted-foreground"
              data-testid="mutant-public-id"
            >{{ line.public_id }}</span>
          </template>
          <template #title>
            <span data-testid="mutant-name">{{ line.name }}</span>
          </template>
        </PageHeader>

        <RouterLink
          v-if="line.variant_count > 0"
          :to="{ path: '/variants', query: { mutant_line_id: line.public_id } }"
          class="link-underline mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-primary"
        >
          {{ t("mutantLines.variants") }}
          <AppIcon name="arrow-right" class="size-4" />
        </RouterLink>

        <section class="mt-8" aria-labelledby="mutant-line-details">
          <h2 id="mutant-line-details" class="font-display text-2xl font-semibold">
            {{ t("mutantLines.generalInfo") }}
          </h2>
          <dl class="mt-4 grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2">
            <div class="bg-card px-4 py-3">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.speciesLabel") }}
              </dt>
              <dd class="mt-1 text-sm">{{ line.species }}</dd>
            </div>
            <div class="bg-card px-4 py-3">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.cultivarLabel") }}
              </dt>
              <dd class="mt-1 text-sm">{{ displayValue(line.cultivar) }}</dd>
            </div>
            <div class="bg-card px-4 py-3">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.mutagenLabel") }}
              </dt>
              <dd class="mt-1 text-sm" data-testid="mutant-mutagen">{{ displayValue(line.mutagen) }}</dd>
            </div>
            <div class="bg-card px-4 py-3">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.generationLabel") }}
              </dt>
              <dd class="mt-1 text-sm">{{ displayValue(line.generation) }}</dd>
            </div>
            <div class="bg-card px-4 py-3">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.linkedVariants") }}
              </dt>
              <dd class="mt-1 font-mono text-sm tabular-nums">{{ line.variant_count }}</dd>
            </div>
            <div class="bg-card px-4 py-3 sm:col-span-2">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.description") }}
              </dt>
              <dd class="mt-1 text-sm">{{ displayValue(line.description) }}</dd>
            </div>
            <div class="bg-card px-4 py-3 sm:col-span-2">
              <dt class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ t("mutantLines.phenotypeObservations") }}
              </dt>
              <dd class="mt-1 text-sm">{{ displayValue(line.phenotype_summary) }}</dd>
            </div>
          </dl>
        </section>

        <section class="mt-10" aria-labelledby="mutant-phenotypes">
          <h2 id="mutant-phenotypes" class="font-display text-2xl font-semibold">
            {{ t("mutantLines.phenotypeObservations") }}
          </h2>
          <p
            class="mt-4 flex items-start gap-2 rounded-xl border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground"
            data-testid="phenotypes-boundary"
          >
            <AppIcon name="info" class="mt-0.5 size-4" />
            <span>{{ t("mutantLines.phenotypeNote") }}</span>
          </p>
          <div class="mt-5">
            <StateBlock
              v-if="phenotypesLoading"
              data-testid="phenotypes-loading"
              variant="loading"
              :title="t('mutantLines.phenotypesLoading')"
            />
            <StateBlock
              v-else-if="phenotypesError"
              data-testid="phenotypes-error"
              variant="error"
              :title="t('mutantLines.phenotypesError')"
            />
            <StateBlock
              v-else-if="phenotypes.length === 0"
              data-testid="phenotypes-empty"
              variant="empty"
              icon="beaker"
              :title="t('mutantLines.phenotypesEmpty')"
            />
            <DataTable
              v-else
              data-testid="phenotypes-table"
              :columns="phenotypeColumns"
              :rows="phenotypes"
              :row-key="(row) => row.id"
              :row-attrs="() => ({ 'data-testid': 'phenotype-row' })"
              :aria-label="t('mutantLines.phenotypeObservations')"
            >
              <template #cell-trait_value="{ row }">{{ displayValue(row.trait_value) }}</template>
              <template #cell-unit="{ row }">{{ displayValue(row.unit) }}</template>
              <template #cell-description="{ row }">{{ displayValue(row.description) }}</template>
            </DataTable>
          </div>
        </section>

        <!-- DB-CORE-2: no internal identifier is ever rendered on the public site. -->
      </article>

      <StateBlock
        v-else
        data-testid="mutant-empty"
        variant="empty"
        icon="beaker"
        :title="t('mutantLines.notFound')"
        class="mt-6"
      />
    </div>
  </PortalLayout>
</template>
