import { TeamOutlined, BranchesOutlined, AimOutlined, ClockCircleOutlined, DeploymentUnitOutlined, ExperimentOutlined, ArrowRightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { http } from "@soymutdb/api-client";
import { fetchHomepageStats } from "@soymutdb/api-client";
import { formatNumber } from "../lib/format";
import { Alert, Typography } from "@/lib/antd";
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
    <div className="space-y-6">
      <div><Typography.Title level={2}>System Overview</Typography.Title><Typography.Text type="secondary">Real-time metrics for the SoyMutDB platform.</Typography.Text></div>

      <section className="rounded-xl border border-primary/20 bg-primary/5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-primary">Next actions</p>
            <h2 className="mt-1 text-lg font-semibold">Keep the data pipeline moving</h2>
            <p className="mt-1 text-sm text-muted-foreground">Start from the real operational workflows instead of decorative management pages.</p>
          </div>
          <Link to="/resource-catalog" className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Open resource catalog <ArrowRightOutlined className="size-4" aria-hidden />
          </Link>
        </div>
      </section>

      {homepageStatsQuery.isError || dashboardStatsQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="Dashboard metrics unavailable"
          description="The API did not return a current metric snapshot; no placeholder values are shown."
          action={<button type="button" className="underline" onClick={() => { void homepageStatsQuery.refetch(); void dashboardStatsQuery.refetch(); }}>Retry</button>}
        />
      ) : null}

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total TeamOutlined"
          value={dashboardStatsQuery.isPending ? "…" : dashboardStatsQuery.isError ? "—" : formatNumber(dashboardStats?.totalUsers ?? 0)}
          icon={<TeamOutlined className="size-5" />}
          trend={dashboardStats?.usersChange !== undefined
            ? { value: `${dashboardStats.usersChange >= 0 ? "+" : ""}${dashboardStats.usersChange.toFixed(1)}%`, positive: dashboardStats.usersChange >= 0 }
            : undefined}
        />
        <StatCard
          label="Active Releases"
          value={homepageStatsQuery.isPending || dashboardStatsQuery.isPending ? "…" : homepageStatsQuery.isError || dashboardStatsQuery.isError ? "—" : formatNumber(homepageStats?.release_count ?? dashboardStats?.activeReleases ?? 0)}
          icon={<BranchesOutlined className="size-5" />}
          trend={dashboardStats?.releasesChange !== undefined
            ? { value: `${dashboardStats.releasesChange >= 0 ? "+" : ""}${dashboardStats.releasesChange.toFixed(1)}%`, positive: dashboardStats.releasesChange >= 0 }
            : undefined}
        />
        <StatCard
          label="Total Variants"
          value={homepageStatsQuery.isPending || dashboardStatsQuery.isPending ? "…" : homepageStatsQuery.isError || dashboardStatsQuery.isError ? "—" : formatNumber(homepageStats?.total_variants ?? dashboardStats?.totalVariants ?? 0)}
          icon={<AimOutlined className="size-5" />}
          trend={dashboardStats?.variantsChange !== undefined
            ? { value: `${dashboardStats.variantsChange >= 0 ? "+" : ""}${dashboardStats.variantsChange.toFixed(1)}%`, positive: dashboardStats.variantsChange >= 0 }
            : undefined}
        />
        <StatCard
          label="Query P95"
          value={dashboardStatsQuery.isPending ? "…" : dashboardStatsQuery.isError ? "—" : `${dashboardStats?.queryP95Ms ?? 0} ms`}
          icon={<ClockCircleOutlined className="size-5" />}
          trend={dashboardStats?.queryP95Change !== undefined
            ? { value: `${dashboardStats.queryP95Change >= 0 ? "+" : ""}${dashboardStats.queryP95Change.toFixed(1)}%`, positive: dashboardStats.queryP95Change < 0 }
            : undefined}
        />
      </div>

      {/* Charts */}
      {seriesError ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">Dashboard trend data unavailable. <button type="button" className="underline" onClick={() => void refetchSeries()}>Retry</button></div> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Suspense fallback={<ChartLoading />}><ImportThroughputChart data={seriesLoading ? [] : importData} /></Suspense>
        <Suspense fallback={<ChartLoading />}><QueryLatencyChart data={seriesLoading ? [] : latencyData} /></Suspense>
      </div>

      <Suspense fallback={<ChartLoading />}><StorageGrowthChart data={seriesLoading ? [] : storageData} /></Suspense>

      {/* Quick stats footer */}
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Genes"
          value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.gene_count ?? 0).toLocaleString()}
          icon={<DeploymentUnitOutlined className="size-5" />}
        />
        <StatCard
          label="Mutant Lines"
          value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.mutant_line_count ?? 0).toLocaleString()}
          icon={<ExperimentOutlined className="size-5" />}
        />
        <StatCard
          label="Seed Accessions"
          value={homepageStatsQuery.isPending ? "…" : homepageStatsQuery.isError ? "—" : (homepageStats?.seed_accessions ?? 0).toLocaleString()}
          icon={<ExperimentOutlined className="size-5" />}
        />
      </div>
    </div>
  );
}

function ChartLoading() {
  return <div className="h-80 animate-pulse rounded-xl border border-border bg-muted/40" />;
}
