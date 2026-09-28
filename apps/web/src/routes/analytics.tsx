/** Analytics route. Live data is the default; demo data requires an explicit opt-in. */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Button, Card, Skeleton, Typography } from "@/lib/antd";
import {
  fetchChromosomeDensity,
  fetchHomepageStats,
  fetchImpactSummary,
  fetchVariantTypeSummary,
  fetchDiscoveryTrend,
} from "@soymutdb/api-client";

const VariantTypeChart = React.lazy(() => import("../components/charts/variant-type-chart").then((m) => ({ default: m.VariantTypeChart })));
const ChromosomeDensityChart = React.lazy(() => import("../components/charts/chromosome-density-chart").then((m) => ({ default: m.ChromosomeDensityChart })));
const ImpactDistribution = React.lazy(() => import("../components/charts/impact-distribution").then((m) => ({ default: m.ImpactDistribution })));
const ReleaseTrend = React.lazy(() => import("../components/charts/release-trend").then((m) => ({ default: m.ReleaseTrend })));

export const Route = createFileRoute("/analytics")({
  component: AnalyticsComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    demo: String(search.demo ?? "").toLowerCase() === "true",
  }),
});

type ImpactItem = { impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER"; count: number };
type ChartPoint = { date: string; cumulative: number; newVariants: number };

const DEMO_VARIANT_TYPES = [
  { name: "SNP", value: 28_415_993 },
  { name: "Indel", value: 3_842_117 },
  { name: "SV", value: 343_960 },
];
const DEMO_IMPACT: ImpactItem[] = [
  { impact: "HIGH", count: 248_193 },
  { impact: "MODERATE", count: 1_842_556 },
  { impact: "LOW", count: 8_923_104 },
  { impact: "MODIFIER", count: 21_488_217 },
];
const DEMO_TREND: ChartPoint[] = [
  { date: "2023-06", cumulative: 12_400_000, newVariants: 12_400_000 },
  { date: "2023-12", cumulative: 18_200_000, newVariants: 5_800_000 },
  { date: "2024-06", cumulative: 24_800_000, newVariants: 6_600_000 },
  { date: "2024-12", cumulative: 28_900_000, newVariants: 4_100_000 },
  { date: "2025-06", cumulative: 32_602_070, newVariants: 3_702_070 },
];

function ChartFallback() {
  return <Skeleton className="h-72 w-full" />;
}

function isDemoEnabled(urlDemo: boolean): boolean {
  return urlDemo || import.meta.env.VITE_DEMO_MODE === "true";
}

function normalizeItems(value: unknown): Array<{ name?: unknown; value?: unknown; impact?: unknown; count?: unknown }> {
  if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).map(([name, item]) => ({ name, value: item }));
  }
  return [];
}

function normalizeVariantTypes(value: unknown): Array<{ name: string; value: number }> {
  return normalizeItems(value)
    .map((item) => ({
      name: String(item.name ?? "Unknown"),
      value: Number(item.value ?? item.count ?? 0),
    }))
    .filter((item) => item.name !== "Unknown" && Number.isFinite(item.value));
}

function normalizeImpact(value: unknown): ImpactItem[] {
  return normalizeItems(value)
    .map((item) => ({
      impact: String(item.impact ?? item.name ?? "").toUpperCase(),
      count: Number(item.count ?? item.value ?? 0),
    }))
    .filter((item): item is ImpactItem =>
      ["HIGH", "MODERATE", "LOW", "MODIFIER"].includes(item.impact)
      && Number.isFinite(item.count),
    );
}

function normalizeTrend(value: unknown): ChartPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => ({
      date: String(item.date ?? item.timestamp ?? ""),
      cumulative: Number(item.cumulative ?? 0),
      newVariants: Number(item.new_variants ?? item.newVariants ?? 0),
    }))
    .filter((item) => item.date.length > 0 && Number.isFinite(item.cumulative) && Number.isFinite(item.newVariants));
}

function AnalyticsComponent() {
  const { t } = useTranslation();
  const { demo: urlDemo } = Route.useSearch();
  const demo = isDemoEnabled(urlDemo);

  const densityQuery = useQuery({
    queryKey: ["chromosome-density"],
    queryFn: () => fetchChromosomeDensity(),
    enabled: !demo,
    staleTime: 10 * 60 * 1000,
  });
  const statsQuery = useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
    enabled: !demo,
    staleTime: 10 * 60 * 1000,
  });
  const variantTypeQuery = useQuery({
    queryKey: ["variant-type-summary"],
    queryFn: () => fetchVariantTypeSummary(),
    enabled: !demo,
    staleTime: 10 * 60 * 1000,
  });
  const impactQuery = useQuery({
    queryKey: ["impact-summary"],
    queryFn: () => fetchImpactSummary(),
    enabled: !demo,
    staleTime: 10 * 60 * 1000,
  });
  const trendQuery = useQuery({
    queryKey: ["discovery-trend"],
    queryFn: () => fetchDiscoveryTrend(365),
    enabled: !demo,
    staleTime: 10 * 60 * 1000,
  });

  const density = demo ? [] : densityQuery.data ?? [];
  const variantTypeData = demo
    ? DEMO_VARIANT_TYPES
    : normalizeVariantTypes(variantTypeQuery.data).length > 0
      ? normalizeVariantTypes(variantTypeQuery.data)
      : statsQuery.data
        ? [
          { name: "SNP", value: statsQuery.data.snp_count },
          { name: "Indel", value: statsQuery.data.indel_count },
          { name: "SV", value: statsQuery.data.sv_count },
        ].filter((item) => Number.isFinite(item.value))
        : [];
  const impactData = demo ? DEMO_IMPACT : normalizeImpact(impactQuery.data);
  const trendData = demo ? DEMO_TREND : normalizeTrend(trendQuery.data);

  return (
    <div className="container-prose section-rhythm">
      {demo ? (
        <div className="mb-6 rounded-lg border-2 border-amber-500 bg-amber-100 px-4 py-3 text-sm font-semibold text-amber-950 dark:bg-amber-950/40 dark:text-amber-100" role="status">
          Demo mode is enabled. The charts below use synthetic example data and are not database measurements.
        </div>
      ) : null}
      <p className="eyebrow">{t("analytics.title")}</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("analytics.subtitle")}</h1>

      <div className="mt-10 grid gap-4 lg:grid-cols-2">
        <AnalyticsCard title={t("analytics.chromosomeDensity")} description={t("analytics.totalByChromosome")} loading={!demo && densityQuery.isLoading} error={!demo && densityQuery.isError} onRetry={() => void densityQuery.refetch()}>
          <React.Suspense fallback={<ChartFallback />}><ChromosomeDensityChart data={density.map((d) => ({ chromosome: d.chromosome, variantCount: d.variant_count }))} /></React.Suspense>
        </AnalyticsCard>
        <AnalyticsCard title={t("analytics.variantTypes")} description="SNP / Indel / SV distribution" loading={!demo && (variantTypeQuery.isLoading || statsQuery.isLoading)} error={!demo && variantTypeQuery.isError && statsQuery.isError} onRetry={() => { void variantTypeQuery.refetch(); void statsQuery.refetch(); }}>
          <React.Suspense fallback={<ChartFallback />}><VariantTypeChart data={variantTypeData} /></React.Suspense>
        </AnalyticsCard>
        <AnalyticsCard title={t("analytics.impactSummary")} description="Variant count by predicted impact" loading={!demo && impactQuery.isLoading} error={!demo && impactQuery.isError} onRetry={() => void impactQuery.refetch()}>
          <React.Suspense fallback={<ChartFallback />}><ImpactDistribution data={impactData} /></React.Suspense>
        </AnalyticsCard>
        <AnalyticsCard title="Release Trend" description="Cumulative variant count over releases" loading={!demo && trendQuery.isLoading} error={!demo && trendQuery.isError} onRetry={() => void trendQuery.refetch()}>
          <React.Suspense fallback={<ChartFallback />}><ReleaseTrend data={trendData} /></React.Suspense>
        </AnalyticsCard>
      </div>
    </div>
  );
}

function AnalyticsCard({ title, description, loading, error, onRetry, children }: { title: string; description: string; loading: boolean; error: boolean; onRetry: () => void; children: React.ReactNode }) {
  return (
    <Card title={<><Typography.Title level={5}>{title}</Typography.Title><Typography.Text type="secondary">{description}</Typography.Text></>}>
      {loading ? <ChartFallback /> : error ? <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"><p className="text-sm text-destructive">Live data unavailable.</p><Button htmlType="button" type="default" size="small" onClick={onRetry}>Retry</Button></div> : children}
    </Card>
  );
}
