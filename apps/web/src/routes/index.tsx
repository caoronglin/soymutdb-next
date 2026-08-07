/** Public home page. All displayed statistics and charts come from the API. */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  Search,
  Microscope,
  FlaskConical,
  BarChart3,
  Sprout,
  BookOpen,
  ArrowRight,
  ArrowUpRight,
  Database,
  Layers,
  Beaker,
  Download,
  Command as CmdIcon,
  Dna,
} from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Skeleton,
  StatCard,
  EmptyState,
} from "@soymutdb/ui";
import { fetchHomepageStats, fetchChromosomeDensity, fetchImpactSummary } from "@soymutdb/api-client";
import { ChromosomeHero } from "../components/chromosome-hero";
import { DnaBackground } from "../components/dna-background";

const ChromosomeDensityChart = React.lazy(() =>
  import("../components/charts/chromosome-density-chart").then((m) => ({ default: m.ChromosomeDensityChart })),
);
const ImpactDistribution = React.lazy(() =>
  import("../components/charts/impact-distribution").then((m) => ({ default: m.ImpactDistribution })),
);

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

type ImpactItem = {
  impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER";
  count: number;
};

function HomeComponent() {
  const { t } = useTranslation();
  const [searchValue, setSearchValue] = React.useState("");
  const navigate = Route.useNavigate();

  const statsQuery = useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
    staleTime: 10 * 60 * 1000,
  });

  const densityQuery = useQuery({
    queryKey: ["chromosome-density"],
    queryFn: () => fetchChromosomeDensity(),
    staleTime: 10 * 60 * 1000,
  });

  const impactQuery = useQuery({
    queryKey: ["impact-summary"],
    queryFn: () => fetchImpactSummary(),
    staleTime: 10 * 60 * 1000,
  });

  const stats = statsQuery.data;
  const density = densityQuery.data ?? [];
  const impactData = React.useMemo<ImpactItem[]>(() => {
    const source = impactQuery.data;
    if (!source || typeof source !== "object") return [];
    const raw = Array.isArray(source)
      ? source
      : Object.entries(source as Record<string, unknown>).map(([impact, count]) => ({ impact, count }));
    return raw
      .map((item) => {
        if (!item || typeof item !== "object") return { impact: undefined, count: undefined };
        const record = item as { impact?: unknown; name?: unknown; count?: unknown; value?: unknown };
        return {
          impact: String(record.impact ?? record.name ?? "").toUpperCase(),
          count: Number(record.count ?? record.value),
        };
      })
      .filter((item): item is ImpactItem =>
        ["HIGH", "MODERATE", "LOW", "MODIFIER"].includes(item.impact ?? "")
        && Number.isFinite(item.count),
      );
  }, [impactQuery.data]);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchValue.trim();
    if (!q) return;
    navigate({ to: "/search", search: { q, tissue: "", treatment: "", min_fpkm: undefined } });
  };

  const openPalette = React.useCallback(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }));
  }, []);

  return (
    <>
      <section className="relative overflow-hidden border-b bg-gradient-accent">
        <DnaBackground />
        <div className="container-prose relative z-10 section-rhythm !py-16 md:!py-28">
          <div className="grid items-center gap-12 lg:grid-cols-[1.1fr_1fr]">
            <div>
              <p className="eyebrow inline-flex items-center gap-2">
                <span className="relative flex size-2">
                  <span className="relative inline-flex size-2 rounded-full bg-primary" aria-hidden />
                </span>
                {stats?.last_release_name ? `${t("home.newRelease")} · ${stats.last_release_name}` : t("home.newRelease")}
              </p>
              <h1 className="mt-5 font-display text-[2.75rem] font-semibold leading-[1.05] tracking-tight md:text-[3.75rem]">
                <span className="block">{t("home.title")}</span>
                <span className="text-gradient block">{t("home.titleHighlight")}</span>
              </h1>
              <p className="mt-6 max-w-xl text-base leading-relaxed text-muted-foreground md:text-lg">{t("home.subtitle")}</p>
              <form onSubmit={onSearch} className="mt-8 max-w-xl" role="search">
                <div className="group relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <input
                    type="search"
                    value={searchValue}
                    onChange={(e) => setSearchValue(e.target.value)}
                    placeholder={t("home.searchPlaceholder")}
                    aria-label={t("nav.search")}
                    className="h-14 w-full rounded-xl border border-input bg-card/80 pl-12 pr-32 text-base shadow-sm outline-none backdrop-blur transition-all placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  <Button type="submit" size="lg" className="absolute right-1.5 top-1.5 btn-glow">
                    {t("home.search")} <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">{t("home.searchExamples")}</p>
                  <button type="button" onClick={openPalette} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
                    <CmdIcon className="size-3" aria-hidden /> <span>Quick open</span> <kbd>⌘K</kbd>
                  </button>
                </div>
              </form>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button asChild size="lg" variant="hero" className="btn-glow">
                  <Link to="/browser" search={{ assembly: "Wm82.a4.v1", locus: "chr01" }}><Microscope className="size-4" aria-hidden />{t("home.browseGenome")}</Link>
                </Button>
                <Button variant="outline" size="lg" asChild><Link to="/blast"><FlaskConical className="size-4" aria-hidden />{t("home.blastSearch")}</Link></Button>
                <Button variant="ghost" size="lg" asChild><Link to="/downloads"><Download className="size-4" aria-hidden />{t("home.downloads")}</Link></Button>
              </div>
            </div>

            <div className="relative rounded-2xl border bg-card/80 p-6 shadow-lg backdrop-blur-sm md:p-8">
              <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-primary/40 to-transparent" aria-hidden />
              <div className="mb-5 flex items-center justify-between">
                <div><p className="eyebrow">Glycine max</p><p className="mt-1 font-display text-sm font-medium">Variant density map</p></div>
                <span className="rounded-md bg-muted px-2 py-1 font-mono text-[11px] text-muted-foreground">Wm82.a4.v1</span>
              </div>
              {densityQuery.isLoading ? <Skeleton className="h-96 w-full" /> : densityQuery.isError ? <DataErrorState message="Chromosome data unavailable." onRetry={() => void densityQuery.refetch()} /> : <ChromosomeHero data={density.map((d) => ({ chromosome: d.chromosome, variantCount: d.variant_count, lengthBp: d.length_bp }))} />}
            </div>
          </div>
        </div>
      </section>

      <section className="container-prose section-rhythm">
        <div className="mb-10 flex items-end justify-between gap-4">
          <div><p className="eyebrow">{t("home.statsTitle")}</p><h2 className="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">{t("home.statsSubtitle")}</h2></div>
          {stats?.last_release_date ? <p className="hidden text-sm text-muted-foreground sm:block">Updated <span className="font-mono">{stats.last_release_date}</span></p> : null}
        </div>
        {statsQuery.isError ? <DataErrorState message="Database statistics unavailable." onRetry={() => void statsQuery.refetch()} /> : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6 [&>*]:h-full">
            <StatCard label={t("home.totalVariants")} value={formatStat(stats?.total_variants)} icon={<Dna className="size-5" />} />
            <StatCard label={t("home.genes")} value={formatStat(stats?.gene_count)} icon={<Layers className="size-5" />} />
            <StatCard label={t("home.mutantLines")} value={formatStat(stats?.mutant_line_count)} icon={<Beaker className="size-5" />} />
            <StatCard label={t("home.snps")} value={formatStat(stats?.snp_count)} icon={<Dna className="size-5" />} />
            <StatCard label={t("home.indels")} value={formatStat(stats?.indel_count)} icon={<Dna className="size-5" />} />
            <StatCard label={t("home.seedAccessions")} value={formatStat(stats?.seed_accessions)} icon={<Sprout className="size-5" />} />
          </div>
        )}
      </section>

      <section className="border-y bg-muted/30 bg-gradient-accent">
        <div className="container-prose section-rhythm">
          <div className="mb-10"><p className="eyebrow">{t("home.dataOverview")}</p><h2 className="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">{t("home.dataOverviewDesc")}</h2></div>
          <div className="grid gap-6 lg:grid-cols-2 [&>*]:h-full">
            <Card className="flex h-full flex-col"><CardHeader><CardTitle>{t("home.chromosomeDistribution")}</CardTitle><CardDescription>{t("home.chromosomeDistributionDesc")}</CardDescription></CardHeader><CardContent className="flex-1">
              {densityQuery.isLoading ? <Skeleton className="h-72 w-full" /> : densityQuery.isError ? <DataErrorState message="Chromosome data unavailable." onRetry={() => void densityQuery.refetch()} /> : <React.Suspense fallback={<Skeleton className="h-72 w-full" />}><ChromosomeDensityChart data={density.map((d) => ({ chromosome: d.chromosome, variantCount: d.variant_count }))} /></React.Suspense>}
            </CardContent></Card>
            <Card className="flex h-full flex-col"><CardHeader><CardTitle>{t("home.impactDistribution")}</CardTitle><CardDescription>{t("home.impactDistributionDesc")}</CardDescription></CardHeader><CardContent className="flex-1">
              {impactQuery.isLoading ? <Skeleton className="h-64 w-full" /> : impactQuery.isError ? <DataErrorState message="Impact data unavailable." onRetry={() => void impactQuery.refetch()} /> : <React.Suspense fallback={<Skeleton className="h-64 w-full" />}><ImpactDistribution data={impactData} /></React.Suspense>}
            </CardContent></Card>
          </div>
        </div>
      </section>

      <section className="container-prose section-rhythm">
        <div className="mb-10 max-w-2xl"><p className="eyebrow">{t("home.featuresTitle")}</p><h2 className="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">{t("home.featuresSubtitle")}</h2></div>
        <div className="grid auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3 [&>*]:h-full">
          {FEATURES.map((feature) => { const Icon = feature.icon; return <Card key={feature.to} className="group flex h-full flex-col"><CardContent className="flex flex-1 flex-col p-6"><div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent/70 text-accent-foreground"><Icon className="size-5" aria-hidden /></div><h3 className="mt-4 font-display text-lg font-semibold">{t(feature.titleKey)}</h3><p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{t(feature.descKey)}</p><Link to={feature.to} className="link-underline mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary">{t("home.learnMore")}<ArrowRight className="size-3.5" aria-hidden /></Link></CardContent></Card>; })}
        </div>
      </section>

      <section className="relative overflow-hidden border-t">
        <div className="absolute inset-0 bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)]" aria-hidden />
        <div className="container-prose relative z-10 section-rhythm !py-16 text-primary-foreground">
          <div className="grid items-center gap-8 lg:grid-cols-[1.5fr_1fr]">
            <div><p className="eyebrow !text-primary-foreground/70">{t("home.latestRelease")}</p><h2 className="mt-3 font-display text-3xl font-semibold tracking-tight md:text-4xl">{stats?.last_release_name ?? "—"}</h2><p className="mt-4 max-w-xl text-primary-foreground/80 leading-relaxed">{t("home.latestReleaseDesc")}</p><div className="mt-6 flex flex-wrap gap-3"><Button variant="secondary" size="lg" asChild className="btn-glow"><Link to="/downloads"><Database className="size-4" aria-hidden />{t("home.downloadData")}</Link></Button><Button variant="outline" size="lg" asChild className="border-primary-foreground/30 bg-transparent text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"><Link to="/analytics" search={{ demo: false }}><BarChart3 className="size-4" aria-hidden />{t("nav.analytics")}<ArrowUpRight className="size-3.5" aria-hidden /></Link></Button></div></div>
            <dl className="grid grid-cols-2 gap-4"><ReleaseStat label={t("home.totalVariants")} value={stats?.total_variants} /><ReleaseStat label={t("home.mutantLines")} value={stats?.mutant_line_count} /><ReleaseStat label={t("home.genes")} value={stats?.gene_count} /><ReleaseStat label={t("home.seedAccessions")} value={stats?.seed_accessions} /></dl>
          </div>
        </div>
      </section>
    </>
  );
}

function formatStat(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString();
}

function ReleaseStat({ label, value }: { label: string; value: number | null | undefined }) {
  return <div className="rounded-xl border border-primary-foreground/15 bg-primary-foreground/10 p-4 backdrop-blur-sm"><dt className="text-xs text-primary-foreground/70">{label}</dt><dd className="mt-1 font-display text-2xl font-semibold tabular-nums">{formatStat(value)}</dd></div>;
}

function DataErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"><p className="text-sm text-destructive">{message}</p><Button type="button" variant="outline" size="sm" onClick={onRetry}>Retry</Button></div>;
}

const FEATURES: ReadonlyArray<{ to: string; titleKey: string; descKey: string; icon: React.ComponentType<{ className?: string }> }> = [
  { to: "/browser", titleKey: "home.featureGenomeBrowser", descKey: "home.featureGenomeBrowserDesc", icon: Microscope },
  { to: "/variants", titleKey: "home.featureVariantSearch", descKey: "home.featureVariantSearchDesc", icon: Search },
  { to: "/blast", titleKey: "home.featureBlast", descKey: "home.featureBlastDesc", icon: FlaskConical },
  { to: "/analytics", titleKey: "home.featureAnalytics", descKey: "home.featureAnalyticsDesc", icon: BarChart3 },
  { to: "/seed-request", titleKey: "home.featureSeeds", descKey: "home.featureSeedsDesc", icon: Sprout },
  { to: "/help", titleKey: "home.featureDocumentation", descKey: "home.featureDocumentationDesc", icon: BookOpen },
];
