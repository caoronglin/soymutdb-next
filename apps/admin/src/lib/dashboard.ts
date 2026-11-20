import { useQuery } from "@tanstack/react-query";
import { fetchHomepageStats, http } from "@soymutdb/api-client";

export interface ImportThroughputPoint {
  date: string;
  imported: number;
  failed: number;
}

export interface QueryLatencyPoint {
  date: string;
  p50: number;
  p95: number;
  p99: number;
}

export interface StorageGrowthPoint {
  date: string;
  bytes: number;
}

export interface DashboardStats {
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
  import_throughput?: ImportThroughputPoint[];
  query_latency?: QueryLatencyPoint[];
  storage_growth?: StorageGrowthPoint[];
  importThroughput?: ImportThroughputPoint[];
  queryLatency?: QueryLatencyPoint[];
  storageGrowth?: StorageGrowthPoint[];
}

export interface DashboardData {
  homepage: ReturnType<typeof useHomepageStats>;
  stats: ReturnType<typeof useAdminDashboardStats>;
  series: ReturnType<typeof useAdminDashboardSeries>;
  importThroughput: ImportThroughputPoint[];
  queryLatency: QueryLatencyPoint[];
  storageGrowth: StorageGrowthPoint[];
}

function useHomepageStats(refetchInterval?: number) {
  return useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
    refetchInterval,
  });
}

function useAdminDashboardStats(refetchInterval?: number) {
  return useQuery<DashboardStats>({
    queryKey: ["admin-dashboard-stats"],
    queryFn: () => http.get<DashboardStats>("/admin/dashboard-stats"),
    refetchInterval,
  });
}

function useAdminDashboardSeries(refetchInterval?: number) {
  return useQuery<DashboardSeriesResponse>({
    queryKey: ["admin-dashboard-series"],
    queryFn: () => http.get<DashboardSeriesResponse>("/admin/dashboard-series"),
    refetchInterval,
  });
}

/** Metric queries shared by the Welcome, Analysis and Monitor workbenches. */
export function useDashboardData(refetchInterval?: number): DashboardData {
  const homepage = useHomepageStats(refetchInterval);
  const stats = useAdminDashboardStats(refetchInterval);
  const series = useAdminDashboardSeries(refetchInterval);

  return {
    homepage,
    stats,
    series,
    importThroughput: series.data?.import_throughput ?? series.data?.importThroughput ?? [],
    queryLatency: series.data?.query_latency ?? series.data?.queryLatency ?? [],
    storageGrowth: series.data?.storage_growth ?? series.data?.storageGrowth ?? [],
  };
}