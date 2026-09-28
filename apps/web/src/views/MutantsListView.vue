<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { Button, Input, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import PageHeader from "../components/table/PageHeader.vue";
import DataTable from "../components/table/DataTable.vue";
import FilterCard from "../components/table/FilterCard.vue";
import FilterField from "../components/table/FilterField.vue";
import type { TableColumn } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import { mutantLinesQueryOptions } from "../lib/query-options";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

// Public mutant-line browser (Phase F). Lists released mutant lines by public
// identifier (DB-CORE-2): the response carries ONLY public_id, never an internal
// persistence key, and the cache key is scoped by release + site variant
// (DB-CORE-6). The mutagen filter is URL-backed state: /mutants?mutagen=EMS
// survives reload, back/forward, and sharing (plan.md §17).
const MUTAGEN_LIMIT = 50;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const mutagen = computed(() => (route.query.mutagen ? String(route.query.mutagen) : ""));
const input = ref(mutagen.value);
watch(mutagen, (value) => {
  input.value = value;
});

const query = useQuery(
  computed(() =>
    mutantLinesQueryOptions({
      mutagen: mutagen.value || undefined,
      limit: MUTAGEN_LIMIT,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const lines = computed(() => toValue(query.data) ?? []);

function applyFilter() {
  const next = input.value.trim();
  void router.replace({
    path: "/mutants",
    query: next ? { mutagen: next } : {},
  });
}

function clearFilter() {
  input.value = "";
  void router.replace({ path: "/mutants", query: {} });
}

const columns: TableColumn[] = [
  { id: "name", header: t("mutantLines.lineName"), primary: true },
  { id: "cultivar", header: t("mutantLines.cultivarLabel") },
  { id: "mutagen", header: t("mutantLines.mutagenLabel") },
  { id: "variant_count", header: t("mutantLines.variantCount"), numeric: true, align: "right" },
];
</script>

<template>
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <PageHeader
        :eyebrow="t('nav.mutantLines')"
        :title="t('mutantLines.title')"
        :description="t('mutantLines.subtitle')"
      />

      <FilterCard @submit="applyFilter">
        <FilterField :label="t('mutantLines.exactMutagen')" for-id="mutagen-filter">
          <Input
            id="mutagen-filter"
            v-model:value="input"
            class="w-full max-w-xs"
            :placeholder="t('mutantLines.mutagenPlaceholder')"
            data-testid="mutagen-filter"
            @change="applyFilter"
          />
        </FilterField>

        <template #actions>
          <Button type="primary" data-testid="mutants-filter-apply" @click="applyFilter">
            {{ t("common.apply") }}
          </Button>
          <Button v-if="mutagen" data-testid="mutants-filter-clear" @click="clearFilter">
            {{ t("common.clear") }}
          </Button>
        </template>
      </FilterCard>

      <section class="mt-4" :aria-label="t('mutantLines.results')">
        <StateBlock
          v-if="isLoading"
          data-testid="mutants-loading"
          variant="loading"
          :title="t('common.loading')"
        />
        <StateBlock
          v-else-if="isError"
          data-testid="mutants-error"
          variant="error"
          :title="t('mutantLines.loadError')"
        />
        <template v-else>
          <p v-if="lines.length === 0" data-testid="mutants-empty" class="text-sm text-muted-foreground">
            {{ t("mutantLines.emptyNoResult") }}
            <span v-if="mutagen"> {{ t("mutantLines.emptyForMutagen", { mutagen }) }}</span>.
          </p>
          <DataTable
            v-else
            data-testid="mutants-results"
            :columns="columns"
            :rows="lines"
            responsive
            :aria-label="t('mutantLines.results')"
            :row-key="(row) => row.public_id"
            :row-attrs="(row) => ({ 'data-testid': 'mutant-row', 'data-public-id': row.public_id })"
            :emptyTitle="t('mutantLines.noResults')"
          >
            <template #cell-name="{ row }">
              <RouterLink
                :to="{ path: `/mutants/${row.public_id}` }"
                class="link-underline font-medium text-primary"
              >
                {{ row.name }}
              </RouterLink>
              <!-- The public identifier is the stable, shareable identity of the
                   row (DB-CORE-2): it stays visible next to the display name. -->
              <span class="mt-0.5 block font-mono text-xs text-muted-foreground">
                {{ row.public_id }}
              </span>
            </template>
            <template #cell-cultivar="{ row }">{{ row.cultivar ?? "—" }}</template>
            <template #cell-mutagen="{ row }">
              <Tag v-if="row.mutagen" class="font-mono text-[10px]">{{ row.mutagen }}</Tag>
              <span v-else class="text-muted-foreground">—</span>
            </template>
            <template #cell-variant_count="{ row }">
              {{ row.variant_count == null ? "—" : row.variant_count.toLocaleString() }}
            </template>
          </DataTable>
        </template>
      </section>
    </div>
  </PortalLayout>
</template>
