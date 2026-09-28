<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.dashboard.systemOverview', { defaultValue: 'System Overview' })"
      :description="t('admin.dashboard.metricsSubtitle', { defaultValue: 'Real-time metrics for the SoyMutDB platform.' })"
    />

    <section class="rounded-xl border border-primary/20 bg-primary/5 p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wider text-primary">
            {{ t("admin.dashboard.nextActions", { defaultValue: "Next actions" }) }}
          </p>
          <h2 class="mt-1 text-lg font-semibold">{{ t("admin.dashboard.pipelineHeadline", { defaultValue: "Keep the data pipeline moving" }) }}</h2>
          <p class="mt-1 max-w-2xl text-sm text-muted-foreground">
            {{ t("admin.dashboard.pipelineDesc", { defaultValue: "Start from the real operational workflows instead of decorative management pages." }) }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <RouterLink
            to="/imports"
            class="inline-flex min-h-9 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground"
            data-testid="dashboard-next-imports"
          >
            {{ t("admin.imports") }}
          </RouterLink>
          <RouterLink
            to="/resource-catalog"
            class="inline-flex min-h-9 items-center rounded-md border border-border bg-card px-3 text-sm"
            data-testid="dashboard-next-catalog"
          >
            {{ t("admin.dashboard.openResourceCatalog", { defaultValue: "Open Resource Catalog" }) }}
          </RouterLink>
        </div>
      </div>
    </section>

    <!-- Operational metrics. Each tile renders its own pending/error marker, so
         one unavailable endpoint cannot blank the whole row. -->
    <section aria-labelledby="dashboard-metrics-heading">
      <h2 id="dashboard-metrics-heading" class="admin-section-title">
        {{ t("admin.dashboard.systemOverview", { defaultValue: "System Overview" }) }}
      </h2>
      <p v-if="metricsUnavailable" class="admin-state admin-state--error mt-2" data-testid="dashboard-metrics-error">
        <span class="admin-state-title">{{ t("admin.dashboard.metricsUnavailable", { defaultValue: "Metrics unavailable" }) }}</span>
        <span>{{ t("admin.dashboard.metricsUnavailableDesc", { defaultValue: "The metrics endpoints did not answer; the release and content APIs below are unaffected." }) }}</span>
        <span class="admin-page-actions mt-1">
          <Button size="small" data-testid="dashboard-metrics-retry" @click="refetchMetrics">
            {{ t("admin.dashboard.retry", { defaultValue: "Retry" }) }}
          </Button>
        </span>
      </p>

      <div class="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <AdminStatCard
          v-for="card in metricCards"
          :key="card.key"
          :label="card.label"
          :value="card.value"
          :trend="card.trend"
          :testid="'dashboard-stat-' + card.key"
        />
      </div>
    </section>

    <!-- Series charts. The endpoint is optional for this deployment, so its
         absence is stated rather than rendered as an empty frame. -->
    <section aria-labelledby="dashboard-charts-heading">
      <h2 id="dashboard-charts-heading" class="admin-section-title">
        {{ t("admin.dashboard.metricsSubtitle", { defaultValue: "Real-time metrics for the SoyMutDB platform." }) }}
      </h2>
      <AdminState
        v-if="seriesQuery.isPending.value"
        state="loading"
        testid="dashboard-charts-loading"
        :rows="3"
        class="mt-2"
      />
      <p
        v-else-if="seriesQuery.isError.value"
        class="admin-state admin-state--error mt-2"
        data-testid="dashboard-charts-error"
      >
        {{ t("admin.dashboard.metricsUnavailable", { defaultValue: "Metrics unavailable" }) }}
      </p>
      <div v-else class="mt-3 grid gap-4 lg:grid-cols-3">
        <AdminSeriesChart
          :title="t('admin.imports')"
          :labels="importSeries.labels"
          :series="importSeries.series"
          variant="bar"
        />
        <AdminSeriesChart
          :title="t('admin.dashboard.queryP95', { defaultValue: 'Query P95 (ms)' })"
          :labels="latencySeries.labels"
          :series="latencySeries.series"
        />
        <AdminSeriesChart
          :title="t('admin.dashboard.totalVariants', { defaultValue: 'Total Variants' })"
          :labels="storageSeries.labels"
          :series="storageSeries.series"
        />
      </div>
    </section>

    <!-- Active release + release list: the releases query owns both. -->
    <AdminState v-if="releasesQuery.isPending.value" state="loading" testid="dashboard-loading" />
    <AdminState
      v-else-if="releasesQuery.isError.value"
      state="error"
      testid="dashboard-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="dashboard-retry" @click="releasesQuery.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>

    <template v-else>
      <AdminCard :title="t('releases.active')" testid="dashboard-active-release">
        <p v-if="!activeRelease" class="text-sm text-muted-foreground" data-testid="dashboard-no-active">
          {{ t("common.noData") }}
        </p>
        <dl v-else class="grid gap-4 sm:grid-cols-3" data-testid="dashboard-active">
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.releaseName") }}</dt>
            <dd class="font-mono text-sm" data-testid="dashboard-release-id">{{ activeRelease.id }}</dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.status") }}</dt>
            <dd><AdminStatusTag :status="activeRelease.status" /></dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.assembly") }}</dt>
            <dd class="font-mono text-xs">{{ activeRelease.assembly_name }}</dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.variantCount") }}</dt>
            <dd data-testid="dashboard-variants">{{ formatNumber(activeRelease.variant_count) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.geneCount") }}</dt>
            <dd>{{ formatNumber(activeRelease.gene_count) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">{{ t("releases.mutantLineCount") }}</dt>
            <dd>{{ formatNumber(activeRelease.mutant_line_count) }}</dd>
          </div>
        </dl>
      </AdminCard>

      <AdminCard :title="t('admin.releases')" testid="dashboard-releases-card">
        <p
          v-if="releases.length === 0"
          class="text-sm text-muted-foreground"
          data-testid="dashboard-releases-empty"
        >
          {{ t("admin.dashboardStats.releasesEmpty") }}
        </p>
        <div v-else class="admin-table-wrap">
          <table class="admin-table" data-testid="dashboard-releases">
            <thead>
              <tr>
                <th scope="col">{{ t("releases.releaseName") }}</th>
                <th scope="col">{{ t("releases.status") }}</th>
                <th scope="col">{{ t("releases.assembly") }}</th>
                <th scope="col" class="admin-table-num">{{ t("releases.variantCount") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="release in releases" :key="String(release.id)" data-testid="dashboard-release-row">
                <td class="font-mono text-xs">
                  {{ release.id }}
                  <span v-if="release.is_active" class="ms-2 text-xs text-primary">
                    ({{ t("releases.active") }})
                  </span>
                </td>
                <td><AdminStatusTag :status="release.status" /></td>
                <td class="font-mono text-xs">{{ release.assembly_name }}</td>
                <td class="admin-table-num">{{ formatNumber(release.variant_count) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </AdminCard>
    </template>

    <AdminCard :title="t('admin.dashboardStats.analyticsHeading')" testid="dashboard-analytics">
      <template #actions>
        <label class="admin-field">
          {{ t("admin.dashboardStats.windowLabel") }}
          <select
            v-model.number="analyticsDays"
            class="admin-control"
            data-testid="dashboard-analytics-days"
          >
            <option :value="7">7</option>
            <option :value="30">30</option>
            <option :value="90">90</option>
          </select>
        </label>
      </template>

      <AdminState v-if="analyticsQuery.isPending.value" state="loading" testid="dashboard-analytics-loading" />
      <AdminState
        v-else-if="analyticsQuery.isError.value"
        state="error"
        testid="dashboard-analytics-error"
        :title="t('admin.dashboardStats.analyticsError')"
      />
      <AdminState
        v-else-if="!analyticsHasTraffic"
        state="empty"
        testid="dashboard-analytics-empty"
        :title="t('admin.dashboardStats.analyticsEmpty')"
      />
      <template v-else>
        <dl class="grid gap-4 sm:grid-cols-2" data-testid="dashboard-analytics-summary">
          <AdminStatCard
            :label="t('admin.analyticsSettings.totalEvents')"
            :value="String(analytics?.total_events ?? 0)"
            testid="dashboard-analytics-total-events"
          />
          <AdminStatCard
            :label="t('admin.analyticsSettings.uniqueSessions')"
            :value="String(analytics?.unique_sessions ?? 0)"
            testid="dashboard-analytics-unique-sessions"
          />
        </dl>

        <div v-if="analytics && analytics.top_pages.length" class="mt-4">
          <h3 class="admin-section-title">{{ t("admin.analyticsSettings.topPages") }}</h3>
          <ul class="mt-1 grid gap-1 text-sm">
            <li v-for="item in analytics.top_pages.slice(0, 5)" :key="item.label" class="flex justify-between gap-3">
              <span class="truncate font-mono text-xs">{{ item.label }}</span>
              <span class="shrink-0 text-xs">{{ item.count }}</span>
            </li>
          </ul>
        </div>
      </template>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import {
  fetchHomepageStats,
  getAdminAnalyticsSummary,
  getReleases,
  type ReleaseSummary,
} from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminSeriesChart from "../components/AdminSeriesChart.vue";
import AdminStatCard from "../components/AdminStatCard.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { adminApi } from "../lib/api";
import { t } from "../lib/i18n";

/**
 * Dashboard — the state an operator checks before touching anything: which
 * release is live, how much is in it, whether anything is waiting, and whether
 * the platform itself is healthy.
 *
 * Every number is served by the API. Where an endpoint is missing the tile says
 * so ("…" while pending, "—" on error) instead of showing a zero that reads as a
 * real measurement; the React console had the same rule.
 */
interface DashboardStats {
  totalUsers: number;
  activeReleases: number;
  totalVariants: number;
  queryP95Ms: number;
  usersChange: number;
  releasesChange: number;
  variantsChange: number;
  queryP95Change: number;
}

/** The series endpoint exists in both snake_case and camelCase shapes. */
interface SeriesResponse {
  import_throughput?: { date: string; imported: number; failed: number }[];
  importThroughput?: { date: string; imported: number; failed: number }[];
  query_latency?: { date: string; p50: number; p95: number; p99: number }[];
  queryLatency?: { date: string; p50: number; p95: number; p99: number }[];
  storage_growth?: { date: string; bytes: number }[];
  storageGrowth?: { date: string; bytes: number }[];
}

const releasesQuery = useQuery({
  queryKey: ["admin", "releases"],
  queryFn: () => getReleases({ page: 1, page_size: 50 }),
});

const statsQuery = useQuery({
  queryKey: ["admin", "dashboard-stats"],
  queryFn: () => adminApi.get<DashboardStats>("/admin/dashboard-stats"),
});

const homepageStatsQuery = useQuery({
  queryKey: ["homepage-stats"],
  queryFn: fetchHomepageStats,
});

const seriesQuery = useQuery({
  queryKey: ["admin", "dashboard-series"],
  queryFn: () => adminApi.get<SeriesResponse>("/admin/dashboard-series"),
});

const analyticsDays = ref(7);
const analyticsQuery = useQuery({
  queryKey: computed(() => ["admin", "analytics", "summary", analyticsDays.value]),
  queryFn: () => getAdminAnalyticsSummary({ days: analyticsDays.value }),
});

const releases = computed(() => toValue(releasesQuery.data) ?? []);
/**
 * The active release comes from the list the API already returns (`is_active`),
 * not from a second endpoint: there is no `GET /releases/current`, and a
 * dashboard that 422s on load is worse than one that reads a field it has.
 */
const activeRelease = computed<ReleaseSummary | null>(
  () => releases.value.find((release) => release.is_active) ?? null,
);
const analytics = computed(() => toValue(analyticsQuery.data));
const analyticsHasTraffic = computed(
  () => analytics.value !== undefined && analytics.value.total_events > 0,
);

const stats = computed(() => toValue(statsQuery.data));
const homepageStats = computed(() => toValue(homepageStatsQuery.data));
const metricsUnavailable = computed(() =>
  [statsQuery, homepageStatsQuery].every((query) => query.isError.value),
);

/** "…" while pending, "—" on error, never a fabricated zero. */
function cell(query: { isPending: { value: boolean }; isError: { value: boolean } }, value: number | undefined): string {
  if (query.isPending.value) return "…";
  if (query.isError.value || value === undefined) return "—";
  return value.toLocaleString();
}

function trend(change: number | undefined): { value: string; positive: boolean } | null {
  if (change === undefined || statsQuery.isError.value) return null;
  const sign = change >= 0 ? "+" : "";
  return { value: `${sign}${change}%`, positive: change >= 0 };
}

const metricCards = computed(() => [
  {
    key: "users",
    label: t("admin.dashboard.totalTeam", { defaultValue: "Team Members" }),
    value: cell(statsQuery, stats.value?.totalUsers),
    trend: trend(stats.value?.usersChange),
  },
  {
    key: "releases",
    label: t("admin.dashboard.activeReleases", { defaultValue: "Active Releases" }),
    value: cell(statsQuery, stats.value?.activeReleases),
    trend: trend(stats.value?.releasesChange),
  },
  {
    key: "variants",
    label: t("admin.dashboard.totalVariants", { defaultValue: "Total Variants" }),
    value: cell(statsQuery, stats.value?.totalVariants),
    trend: trend(stats.value?.variantsChange),
  },
  {
    key: "p95",
    label: t("admin.dashboard.queryP95", { defaultValue: "Query P95 (ms)" }),
    value: cell(statsQuery, stats.value?.queryP95Ms),
    trend: trend(stats.value?.queryP95Change),
  },
  {
    key: "genes",
    label: t("admin.dashboard.genes", { defaultValue: "Genes" }),
    value: cell(homepageStatsQuery, homepageStats.value?.gene_count),
    trend: null,
  },
  {
    key: "mutant-lines",
    label: t("admin.dashboard.mutantLines", { defaultValue: "Mutant Lines" }),
    value: cell(homepageStatsQuery, homepageStats.value?.mutant_line_count),
    trend: null,
  },
  {
    key: "seed-accessions",
    label: t("admin.dashboard.seedAccessions", { defaultValue: "Seed Accessions" }),
    value: cell(homepageStatsQuery, homepageStats.value?.seed_accessions),
    trend: null,
  },
]);

const series = computed(() => toValue(seriesQuery.data));
const importRows = computed(() => series.value?.import_throughput ?? series.value?.importThroughput ?? []);
const latencyRows = computed(() => series.value?.query_latency ?? series.value?.queryLatency ?? []);
const storageRows = computed(() => series.value?.storage_growth ?? series.value?.storageGrowth ?? []);

const importSeries = computed(() => ({
  labels: importRows.value.map((row) => row.date),
  series: [
    { name: "imported", color: "var(--chart-1)", values: importRows.value.map((row) => row.imported) },
    { name: "failed", color: "var(--destructive)", values: importRows.value.map((row) => row.failed) },
  ],
}));

const latencySeries = computed(() => ({
  labels: latencyRows.value.map((row) => row.date),
  series: [
    { name: "p50", color: "var(--chart-2)", values: latencyRows.value.map((row) => row.p50) },
    { name: "p95", color: "var(--chart-1)", values: latencyRows.value.map((row) => row.p95) },
    { name: "p99", color: "var(--chart-5)", values: latencyRows.value.map((row) => row.p99) },
  ],
}));

const storageSeries = computed(() => ({
  labels: storageRows.value.map((row) => row.date),
  series: [
    { name: "bytes", color: "var(--chart-3)", values: storageRows.value.map((row) => row.bytes) },
  ],
}));

function refetchMetrics(): void {
  void statsQuery.refetch();
  void homepageStatsQuery.refetch();
}
</script>
