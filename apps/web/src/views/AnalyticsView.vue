<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import {
  ChartFigure,
  categoryBarChart,
  trendAreaChart,
  type CategoryValue,
  type TrendPoint,
} from "@soymutdb/charts";
import { formatNumber } from "@soymutdb/shared/format";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import {
  chromosomeDensityQueryOptions,
  discoveryTrendQueryOptions,
  effectDistributionQueryOptions,
  impactSummaryQueryOptions,
  mutagenStatisticsQueryOptions,
  variantTypeSummaryQueryOptions,
} from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Visual analytics.
 *
 * Every panel is a plain table first and a chart second: the numbers come from
 * the aggregate endpoints, the chart is drawn through `@soymutdb/charts` (which
 * always ships the exact-value table with it), and an unreachable API produces
 * an error with a retry — never a placeholder series.
 */
const TREND_DAYS = 365;
const site = useSiteContextStore();

const densityQuery = useQuery(chromosomeDensityQueryOptions(siteContext()));
const typesQuery = useQuery(variantTypeSummaryQueryOptions(siteContext()));
const impactQuery = useQuery(impactSummaryQueryOptions(siteContext()));
const effectQuery = useQuery(effectDistributionQueryOptions(siteContext()));
const mutagenQuery = useQuery(mutagenStatisticsQueryOptions(siteContext()));
const trendQuery = useQuery(
  discoveryTrendQueryOptions({ ...siteContext(), days: TREND_DAYS }),
);

function siteContext() {
  return { releaseId: site.releaseId, siteVariant: site.siteVariant };
}

const densityRows = computed<CategoryValue[]>(() =>
  (toValue(densityQuery.data) ?? []).map((item) => ({
    category: item.chromosome,
    value: item.variant_count,
  })),
);
const typeRows = computed<CategoryValue[]>(() =>
  (toValue(typesQuery.data) ?? []).map((item) => ({ category: item.name, value: item.value })),
);
const impactRows = computed<CategoryValue[]>(() =>
  (toValue(impactQuery.data) ?? []).map((item) => ({ category: item.impact, value: item.count })),
);
const mutagenRows = computed<CategoryValue[]>(() =>
  (toValue(mutagenQuery.data) ?? []).map((item) => ({
    category: item.mutagen,
    value: item.count,
  })),
);
const effectRows = computed<CategoryValue[]>(() =>
  (toValue(effectQuery.data) ?? []).map((item) => ({
    category: `${item.effect} (${item.impact})`,
    value: item.count,
  })),
);
const trendRows = computed<TrendPoint[]>(() =>
  (toValue(trendQuery.data) ?? []).map((item) => ({
    date: item.date,
    value: item.cumulative,
  })),
);

const PANELS = computed(() => [
  {
    id: "density",
    title: "Chromosome density",
    rows: densityRows,
    columns: ["Chromosome", "Variants"],
    row: (datum: CategoryValue) => [datum.category, formatNumber(datum.value)],
    definition: () => categoryBarChart(densityRows.value, { valueLabel: "Variants" }),
    query: densityQuery,
  },
  {
    id: "types",
    title: "Variant types",
    rows: typeRows,
    columns: ["Type", "Variants"],
    row: (datum: CategoryValue) => [datum.category, formatNumber(datum.value)],
    definition: () => categoryBarChart(typeRows.value, { valueLabel: "Variants" }),
    query: typesQuery,
  },
  {
    id: "impact",
    title: "Impact summary",
    rows: impactRows,
    columns: ["Impact", "Variants"],
    row: (datum: CategoryValue) => [datum.category, formatNumber(datum.value)],
    definition: () => categoryBarChart(impactRows.value, { valueLabel: "Variants" }),
    query: impactQuery,
  },
  {
    id: "effects",
    title: "Consequence by impact",
    rows: effectRows,
    columns: ["Consequence (impact)", "Variants"],
    row: (datum: CategoryValue) => [datum.category, formatNumber(datum.value)],
    definition: () => categoryBarChart(effectRows.value, { valueLabel: "Variants" }),
    query: effectQuery,
  },
  {
    id: "mutagens",
    title: "Mutagen comparison",
    rows: mutagenRows,
    columns: ["Mutagen", "Lines"],
    row: (datum: CategoryValue) => [datum.category, formatNumber(datum.value)],
    definition: () => categoryBarChart(mutagenRows.value, { valueLabel: "Lines" }),
    query: mutagenQuery,
  },
] as const);

function panelQuery(panel: (typeof PANELS.value)[number]) {
  return panel.query;
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("analytics.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("analytics.subtitle") }}</p>

      <section class="mt-8" aria-labelledby="trend-heading">
        <h2 id="trend-heading" class="text-lg font-medium">{{ t("analytics.discoveryTrend") }}</h2>
        <div class="mt-3 rounded-lg border p-4">
          <p v-if="trendQuery.isPending.value" class="text-sm opacity-70">{{ t("common.loading") }}</p>
          <p v-else-if="trendQuery.isError.value" class="text-sm text-red-700">
            {{ t("common.errorDescription") }}
          </p>
          <ChartFigure
            v-else
            :definition="trendAreaChart(trendRows)"
            :data="trendRows"
            :label="t('analytics.discoveryTrend')"
            :description="t('analytics.trendDescription')"
            :table-columns="['Date', 'Cumulative variants']"
            :table-row="(datum: TrendPoint) => [datum.date, formatNumber(datum.value)]"
            :empty-text="t('analytics.noData')"
          />
        </div>
      </section>

      <div class="mt-8 grid gap-6 lg:grid-cols-2">
        <section v-for="panel in PANELS" :key="panel.id" :aria-labelledby="'panel-' + panel.id">
          <h2 :id="'panel-' + panel.id" class="text-lg font-medium">{{ panel.title }}</h2>
          <p v-if="panelQuery(panel).isPending.value" class="mt-3 text-sm opacity-70">
            {{ t("common.loading") }}
          </p>
          <p v-else-if="panelQuery(panel).isError.value" class="mt-3 text-sm text-red-700">
            {{ t("common.errorDescription") }}
          </p>
          <div v-else class="mt-3 rounded-lg border p-4">
            <ChartFigure
              :definition="panel.definition()"
              :data="panel.rows.value"
              :label="panel.title"
              :table-columns="panel.columns"
              :table-row="panel.row"
              :empty-text="t('analytics.noData')"
            />
          </div>
        </section>
      </div>
    </div>
  </PortalLayout>
</template>
