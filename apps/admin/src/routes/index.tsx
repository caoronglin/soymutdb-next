import { TeamOutlined, BranchesOutlined, AimOutlined, ClockCircleOutlined, DeploymentUnitOutlined, ExperimentOutlined, ArrowRightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import { http } from "@soymutdb/api-client";
import { fetchHomepageStats } from "@soymutdb/api-client";
import { formatNumber } from "../lib/format";
import { Alert, Button, PageContainer } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { lazy, Suspense } from "react";

const ImportThroughputChart = lazy(() => import("../components/charts/import-throughput").then((m) => ({ default: m.ImportThroughputChart })));
const QueryLatencyChart = lazy(() => import("../components/charts/query-latency").then((m) => ({ default: m.QueryLatencyChart })));
const StorageGrowthChart = lazy(() => import("../components/charts/storage-growth").then((m) => ({ default: m.StorageGrowthChart })));

interface ImportThroughputDataPoint { date: string; imported: number; failed: number }
interface QueryLatencyDataPoint { date: string; p50: number; p95: number; p99: number }
interface StorageGrowthDataPoint { date: string; bytes: number }

/** Dashboard system overview statistics. */
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

interface DashboardSeriesResponse {
  import_throughput?: ImportThroughputDataPoint[];
  query_latency?: QueryLatencyDataPoint[];
  storage_growth?: StorageGrowthDataPoint[];
  importThroughput?: ImportThroughputDataPoint[];
  queryLatency?: QueryLatencyDataPoint[];
  storageGrowth?: StorageGrowthDataPoint[];
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const homepageStatsQuery = useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
  });
  const homepageStats = homepageStatsQuery.data;

  const dashboardStatsQuery = useQuery<DashboardStats>({
    queryKey: ["admin-dashboard-stats"],
    queryFn: () => http.get<DashboardStats>("/admin/dashboard-stats"),
  });
  const dashboardStats = dashboardStatsQuery.data;

  const { data: dashboardSeries, isLoading: seriesLoading, isError: seriesError, refetch: refetchSeries } = useQuery<DashboardSeriesResponse>({
    queryKey: ["admin-dashboard-series"],
    queryFn: () => http.get<DashboardSeriesResponse>("/admin/dashboard-series"),
  });

  const importData = dashboardSeries?.import_throughput ?? dashboardSeries?.importThroughput ?? [];
  const latencyData = dashboardSeries?.query_latency ?? dashboardSeries?.queryLatency ?? [];
  const storageData = dashboardSeries?.storage_growth ?? dashboardSeries?.storageGrowth ?? [];

  return (
    <PageContainer
      title={t("admin.dashboard.systemOverview", { defaultValue: "System Overview" })}
      subTitle={t("admin.dashboard.metricsSubtitle", { defaultValue: "Real-time metrics for the SoyMutDB platform." })}
    >
      <div className="space-y-6">
        <section className="rounded-lg border border-primary/20 bg-primary/5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-primary">{t("admin.dashboard.nextActions", { defaultValue: "Next actions" })}</p>
              <h2 className="mt-1 text-lg font-semibold">{t("admin.dashboard.pipelineHeadline", { defaultValue: "Keep the data pipeline moving" })}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("admin.dashboard.pipelineDesc", { defaultValue: "Start from the real operational workflows instead of decorative management pages." })}</p>
            </div>
            {/* This used to point at `/resource-catalog`, which the router
                resolves to `LegacyUnavailablePage`: the console's single primary
                call-to-action opened "this page is unavailable". Imports is the
                live workflow the unavailable page itself recommends. */}
            <div className="flex flex-wrap items-center gap-2">
              <Link to="/imports" className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                {t("admin.dashboard.openImports", { defaultValue: "Open imports" })} <ArrowRightOutlined className="size-4" aria-hidden />
              </Link>
              {/* Visitor analytics lives on its own settings page and, until
                  this link existed, the dashboard had no route to it: the only
                  path was the sidebar entry under Administration. */}
              <Link
                to="/analytics-settings"
                className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-accent"
              >
                {t("admin.dashboard.openAnalytics", { defaultValue: "Visitor analytics" })}
              </Link>
            </div>
          </div>
        </section>

        {homepageStatsQuery.isError || dashboardStatsQuery.isError ? (
          <Alert
            type="error"
            showIcon
            data-testid="dashboard-stats-error"
            title={t("admin.dashboard.metricsUnavailable", { defaultValue: "Dashboard metrics unavailable" })}
            description={t("admin.dashboard.metricsUnavailableDesc", { defaultValue: "The API did not return a current metric snapshot; no placeholder values are shown." })}
            action={
              <Button
                type="link"
                size="small"
                data-testid="dashboard-stats-retry"
                onClick={() => {
                  void homepageStatsQuery.refetch();
                  void dashboardStatsQuery.refetch();
                }}
              >
                {t("admin.dashboard.retry", { defaultValue: "Retry" })}
              </Button>
            }
          />
        ) : null}

        {/* Stat cards.
            `dashboard-stats` + `data-pending` is the browser-gate contract for
            "the metrics APIs it actually calls (homepage stats and
            /admin/dashboard-stats) settled": an errored query leaves the cards
            in the "—" placeholder state instead of a fabricated number, so the
            settled marker is reached in both outcomes. */}
        <div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          data-testid="dashboard-stats"
          data-pending={String(homepageStatsQuery.isPending || dashboardStatsQuery.isPending)}
        >
          <StatCard
            label={t("admin.dashboard.totalTeam", { defaultValue: "Total Team" })}
            value={dashboardStatsQuery.isPending ? "…" : dashboardStatsQuery.isError ? "—" : formatNumber(dashboardStats?.totalUsers ?? 0)}
            icon={<TeamOutlined className="size-5" />}
            trend={dashboardStats?.usersChange !== undefined
              ? { value: `${dashboardStats.usersChange >= 0 ? "+" : ""}${dashboardStats.usersChange.toFixed(1)}%`, positive: dashboardStats.usersChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.activeReleases", { defaultValue: "Active Releases" })}
            value={homepageStatsQuery.isPending || dashboardStatsQuery.isPending ? "…" : homepageStatsQuery.isError || dashboardStatsQuery.isError ? "—" : formatNumber(homepageStats?.release_count ?? dashboardStats?.activeReleases ?? 0)}
            icon={<BranchesOutlined className="size-5" />}
            trend={dashboardStats?.releasesChange !== undefined
              ? { value: `${dashboardStats.releasesChange >= 0 ? "+" : ""}${dashboardStats.releasesChange.toFixed(1)}%`, positive: dashboardStats.releasesChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.totalVariants", { defaultValue: "Total Variants" })}
            value={homepageStatsQuery.isPending || dashboardStatsQuery.isPending ? "…" : homepageStatsQuery.isError || dashboardStatsQuery.isError ? "—" : formatNumber(homepageStats?.total_variants ?? dashboardStats?.totalVariants ?? 0)}
            icon={<AimOutlined className="size-5" />}
            trend={dashboardStats?.variantsChange !== undefined
              ? { value: `${dashboardStats.variantsChange >= 0 ? "+" : ""}${dashboardStats.variantsChange.toFixed(1)}%`, positive: dashboardStats.variantsChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.dashboard.queryP95", { defaultValue: "Query P95" })}
            value={dashboardStatsQuery.isPending ? "…" : dashboardStatsQuery.isError ? "—" : `${dashboardStats?.queryP95Ms ?? 0} ms`}
            icon={<ClockCircleOutlined className="size-5" />}
            trend={dashboardStats?.queryP95Change !== undefined
              ? { value: `${dashboardStats.queryP95Change >= 0 ? "+" : ""}${dashboardStats.queryP95Change.toFixed(1)}%`, positive: dashboardStats.queryP95Change < 0 }
              : undefined}
          />
        </div>

        {/* Charts. `dashboard-trends` + `data-pending` mirrors `dashboard-stats`
            for /admin/dashboard-series, which fails independently of the metric
            snapshot above. */}
        {seriesError ? (
          <Alert
            type="error"
            showIcon
            data-testid="dashboard-series-error"
            title={t("admin.dashboard.trendUnavailable", {
              defaultValue: "Dashboard trend data unavailable.",
            })}
            action={
              <Button type="link" size="small" data-testid="dashboard-series-retry" onClick={() => void refetchSeries()}>
                {t("admin.dashboard.retry", { defaultValue: "Retry" })}
              </Button>
            }
          />
        ) : null}
        <div data-testid="dashboard-trends" data-pending={String(seriesLoading)}>
          <div className="grid gap-4 lg:grid-cols-2">
            <Suspense fallback={<ChartLoading />}><ImportThroughputChart data={seriesLoading ? [] : importData} /></Suspense>
            <Suspense fallback={<ChartLoading />}><QueryLatencyChart data={seriesLoading ? [] : latencyData} /></Suspense>
          </div>

          {/* `GET /admin/dashboard-series` returns `storage_growth: []` on
              every deployment: no reliable storage source exists yet
              (apps/api/app/api/v1/admin.py::admin_dashboard_series says so in
              its own docstring). Rendering the card anyway put a permanent
              "No chart data" panel on the dashboard, which reads as a broken
              widget rather than as a metric that is not measured. The card is
              rendered only when there is something to show. */}
          {!seriesLoading && storageData.length === 0 ? null : (
            <Suspense fallback={<ChartLoading />}><StorageGrowthChart data={seriesLoading ? [] : storageData} /></Suspense>
          )}
        </div>

        {/* Quick stats footer */}
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard
            label={t("admin.dashboard.genes", { defaultValue: "Genes" })}
            value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.gene_count ?? 0).toLocaleString()}
            icon={<DeploymentUnitOutlined className="size-5" />}
          />
          <StatCard
            label={t("admin.dashboard.mutantLines", { defaultValue: "Mutant Lines" })}
            value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.mutant_line_count ?? 0).toLocaleString()}
            icon={<ExperimentOutlined className="size-5" />}
          />
          <StatCard
            label={t("admin.dashboard.seedAccessions", { defaultValue: "Seed Accessions" })}
            value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.seed_accessions ?? 0).toLocaleString()}
            icon={<ExperimentOutlined className="size-5" />}
          />
        </div>
      </div>
    </PageContainer>
  );
}

function ChartLoading() {
  return <div className="h-80 animate-pulse rounded-lg border border-border bg-muted/40" />;
}
