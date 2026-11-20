import { TeamOutlined, BranchesOutlined, AimOutlined, ClockCircleOutlined, DeploymentUnitOutlined, ExperimentOutlined, ArrowRightOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import { formatNumber } from "../lib/format";
import { useDashboardData } from "../lib/dashboard";
import { Alert, Button, PageContainer } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { lazy, Suspense } from "react";

const ImportThroughputChart = lazy(() => import("../components/charts/import-throughput").then((m) => ({ default: m.ImportThroughputChart })));
const QueryLatencyChart = lazy(() => import("../components/charts/query-latency").then((m) => ({ default: m.QueryLatencyChart })));
const StorageGrowthChart = lazy(() => import("../components/charts/storage-growth").then((m) => ({ default: m.StorageGrowthChart })));

/**
 * The console's landing page.
 *
 * It is not a dashboard: the two dashboards live at `/dashboard/analysis` and
 * `/dashboard/monitor`, and the sidebar labels this entry "Welcome". The old
 * name (`DashboardPage`) made three different pages answer to "dashboard", so
 * the component is named for the job it does.
 */
export default function SystemOverviewPage() {
  const { t } = useTranslation();
  const { homepage, stats, series, importThroughput, queryLatency, storageGrowth } = useDashboardData();
  const homepageStats = homepage.data;
  const dashboardStats = stats.data;

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
              {/* One entry point per destination. `/imports` used to be reachable
                  from this button *and* from a "Data imports" card in the
                  shortcut grid below; visitor analytics is a sidebar entry under
                  Administration and does not also need a button here. */}
              <Link to="/imports" className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                {t("admin.dashboard.openImports", { defaultValue: "Open imports" })} <ArrowRightOutlined className="size-4" aria-hidden />
              </Link>
            </div>
          </div>
        </section>

        {homepage.isError || stats.isError ? (
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
                  void homepage.refetch();
                  void stats.refetch();
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
          data-pending={String(homepage.isPending || stats.isPending)}
        >
          <StatCard
            label={t("admin.dashboard.totalTeam", { defaultValue: "Total Team" })}
            value={stats.isPending ? "…" : stats.isError ? "—" : formatNumber(dashboardStats?.totalUsers ?? 0)}
            icon={<TeamOutlined className="size-5" />}
            trend={dashboardStats?.usersChange !== undefined
              ? { value: `${dashboardStats.usersChange >= 0 ? "+" : ""}${dashboardStats.usersChange.toFixed(1)}%`, positive: dashboardStats.usersChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.activeReleases", { defaultValue: "Active Releases" })}
            value={homepage.isPending || stats.isPending ? "…" : homepage.isError || stats.isError ? "—" : formatNumber(homepageStats?.release_count ?? dashboardStats?.activeReleases ?? 0)}
            icon={<BranchesOutlined className="size-5" />}
            trend={dashboardStats?.releasesChange !== undefined
              ? { value: `${dashboardStats.releasesChange >= 0 ? "+" : ""}${dashboardStats.releasesChange.toFixed(1)}%`, positive: dashboardStats.releasesChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.totalVariants", { defaultValue: "Total Variants" })}
            value={homepage.isPending || stats.isPending ? "…" : homepage.isError || stats.isError ? "—" : formatNumber(homepageStats?.total_variants ?? dashboardStats?.totalVariants ?? 0)}
            icon={<AimOutlined className="size-5" />}
            trend={dashboardStats?.variantsChange !== undefined
              ? { value: `${dashboardStats.variantsChange >= 0 ? "+" : ""}${dashboardStats.variantsChange.toFixed(1)}%`, positive: dashboardStats.variantsChange >= 0 }
              : undefined}
          />
          <StatCard
            label={t("admin.dashboard.queryP95", { defaultValue: "Query P95" })}
            value={stats.isPending ? "…" : stats.isError ? "—" : `${dashboardStats?.queryP95Ms ?? 0} ms`}
            icon={<ClockCircleOutlined className="size-5" />}
            trend={dashboardStats?.queryP95Change !== undefined
              ? { value: `${dashboardStats.queryP95Change >= 0 ? "+" : ""}${dashboardStats.queryP95Change.toFixed(1)}%`, positive: dashboardStats.queryP95Change < 0 }
              : undefined}
          />
        </div>

        {/* Route shortcuts into the data surfaces operators act on. The
            dashboard answers "how is the platform doing"; these cards answer
            "where do I go next" without a detour through the sidebar tree. */}
        <section aria-labelledby="dashboard-quick-links-heading">
          <h2 id="dashboard-quick-links-heading" className="text-base font-semibold">
            {t("admin.dashboard.quickLinks", { defaultValue: "Data management shortcuts" })}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("admin.dashboard.quickLinksHint", { defaultValue: "Jump straight to the workflows behind the numbers above." })}
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              {
                key: "releases",
                to: "/releases",
                icon: <BranchesOutlined className="size-5" aria-hidden />,
                title: t("admin.dashboard.shortcuts.releases.title", { defaultValue: "Releases" }),
                description: t("admin.dashboard.shortcuts.releases.description", { defaultValue: "Versions, publication status and record counts." }),
              },
              {
                key: "data-views",
                to: "/data-views",
                icon: <DeploymentUnitOutlined className="size-5" aria-hidden />,
                title: t("admin.dashboard.shortcuts.dataViews.title", { defaultValue: "Multi-dimensional views" }),
                description: t("admin.dashboard.shortcuts.dataViews.description", { defaultValue: "Saved grid, kanban and gallery views over the data." }),
              },
              {
                key: "media",
                to: "/media",
                icon: <AimOutlined className="size-5" aria-hidden />,
                title: t("admin.dashboard.shortcuts.media.title", { defaultValue: "Media library" }),
                description: t("admin.dashboard.shortcuts.media.description", { defaultValue: "Portal images and files used by the public site." }),
              },
            ].map((link) => (
              <Link
                key={link.key}
                to={link.to}
                className="group rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40"
              >
                <div className="flex items-center gap-2 text-primary">
                  {link.icon}
                  <span className="text-sm font-medium text-foreground">{link.title}</span>
                  <ArrowRightOutlined className="ml-auto size-3.5 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{link.description}</p>
              </Link>
            ))}
          </div>
        </section>

        {/* Charts. `dashboard-trends` + `data-pending` mirrors `dashboard-stats`
            for /admin/dashboard-series, which fails independently of the metric
            snapshot above. */}
        {series.isError ? (
          <Alert
            type="error"
            showIcon
            data-testid="dashboard-series-error"
            title={t("admin.dashboard.trendUnavailable", {
              defaultValue: "Dashboard trend data unavailable.",
            })}
            action={
              <Button type="link" size="small" data-testid="dashboard-series-retry" onClick={() => void series.refetch()}>
                {t("admin.dashboard.retry", { defaultValue: "Retry" })}
              </Button>
            }
          />
        ) : null}
        <div data-testid="dashboard-trends" data-pending={String(series.isPending)}>
          <div className="grid gap-4 lg:grid-cols-2">
            <Suspense fallback={<ChartLoading />}><ImportThroughputChart data={series.isPending ? [] : importThroughput} /></Suspense>
            <Suspense fallback={<ChartLoading />}><QueryLatencyChart data={series.isPending ? [] : queryLatency} /></Suspense>
          </div>

          {/* `GET /admin/dashboard-series` returns `storage_growth: []` on
              every deployment: no reliable storage source exists yet
              (apps/api/app/api/v1/admin.py::admin_dashboard_series says so in
              its own docstring). Rendering the card anyway put a permanent
              "No chart data" panel on the dashboard, which reads as a broken
              widget rather than as a metric that is not measured. The card is
              rendered only when there is something to show. */}
          {!series.isPending && storageGrowth.length === 0 ? null : (
            <Suspense fallback={<ChartLoading />}><StorageGrowthChart data={series.isPending ? [] : storageGrowth} /></Suspense>
          )}
        </div>

        {/* Database content snapshot */}
        <section aria-labelledby="dashboard-content-heading">
          <h2 id="dashboard-content-heading" className="text-base font-semibold">
            {t("admin.dashboard.contentOverview", { defaultValue: "Database content" })}
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <StatCard
              label={t("admin.dashboard.genes", { defaultValue: "Genes" })}
              value={homepage.isPending ? "…" : homepage.isError ? "—" : (homepageStats?.gene_count ?? 0).toLocaleString()}
              icon={<DeploymentUnitOutlined className="size-5" />}
            />
            <StatCard
              label={t("admin.dashboard.mutantLines", { defaultValue: "Mutant Lines" })}
              value={homepage.isPending ? "…" : homepage.isError ? "—" : (homepageStats?.mutant_line_count ?? 0).toLocaleString()}
              icon={<ExperimentOutlined className="size-5" />}
            />
            <StatCard
              label={t("admin.dashboard.seedAccessions", { defaultValue: "Seed Accessions" })}
              value={homepage.isPending ? "…" : homepage.isError ? "—" : (homepageStats?.seed_accessions ?? 0).toLocaleString()}
              icon={<ExperimentOutlined className="size-5" />}
            />
          </div>
        </section>
      </div>
    </PageContainer>
  );
}

function ChartLoading() {
  return <div className="h-80 animate-pulse rounded-lg border border-border bg-muted/40" />;
}
