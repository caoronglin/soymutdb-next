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
              <form onSubmit={onSearch} className="mt-9 max-w-xl" role="search">
                <div className="group relative">
                  <Search className="pointer-events-none absolute left-5 top-1/2 size-5 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" aria-hidden />
                  <input
                    type="search"
                    value={searchValue}
                    onChange={(e) => setSearchValue(e.target.value)}
                    placeholder={t("home.searchPlaceholder")}
                    aria-label={t("nav.search")}
                    className="h-16 w-full rounded-2xl border border-input bg-card/90 pl-13 pr-36 text-base shadow-[var(--shadow-md)] outline-none backdrop-blur transition-all placeholder:text-muted-foreground/80 hover:border-ring/40 focus-visible:border-ring focus-visible:shadow-[var(--shadow-glow)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  />
                  <Button type="submit" size="lg" className="absolute right-2 top-2 h-12 btn-glow">
                    {t("home.search")} <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t("home.tryExamples")}</span>
                  {SEARCH_EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() =>
                        navigate({ to: "/search", search: { q: example, tissue: "", treatment: "", min_fpkm: undefined } })
                      }
                      className="rounded-full border border-border/80 bg-card/70 px-3 py-1 font-mono text-xs text-muted-foreground backdrop-blur transition-all hover:-translate-y-px hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
                    >
                      {example}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={openPalette}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <CmdIcon className="size-3" aria-hidden /> <span>Quick open</span> <kbd>⌘K</kbd>
                  </button>
                </div>
              </form>
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

          {/* Task entries — the three primary jobs */}
          <div className="mt-12 grid gap-3 sm:grid-cols-3">
            {TASK_ENTRIES.map((entry) => {
              const Icon = entry.icon;
              return (
                <Link
                  key={entry.to}
                  to={entry.to}
                  className={`group relative flex items-center gap-4 overflow-hidden rounded-2xl border p-4 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:p-5 ${entry.emphasis ? "card-hover-accent border-primary/30 bg-primary/[0.05]" : "bg-card/70 hover:border-primary/25"}`}
                >
                  <span className={`flex size-11 shrink-0 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-105 ${entry.tileClass}`}>
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold tracking-tight">{t(entry.titleKey)}</span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">{t(entry.descKey)}</span>
                  </span>
                  <ArrowRight className="ml-auto size-4 shrink-0 text-muted-foreground/60 transition-all duration-300 group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      <section className="container-prose section-rhythm">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div><p className="eyebrow">{t("home.statsTitle")}</p><h2 className="mt-2 font-display text-2xl font-semibold tracking-tight md:text-3xl">{t("home.statsSubtitle")}</h2></div>
        </div>
        {statsQuery.isError ? <DataErrorState message="Database statistics unavailable." onRetry={() => void statsQuery.refetch()} /> : (
          <>
            <div className="scroll-fade-in overflow-hidden rounded-2xl border bg-card shadow-sm">
              <dl className="grid grid-cols-2 gap-px bg-border/60 sm:grid-cols-3 lg:grid-cols-6">
                <StatCell label={t("home.totalVariants")} value={formatStat(stats?.total_variants)} icon={<Dna className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
                <StatCell label={t("home.genes")} value={formatStat(stats?.gene_count)} icon={<Layers className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
                <StatCell label={t("home.mutantLines")} value={formatStat(stats?.mutant_line_count)} icon={<Beaker className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
                <StatCell label={t("home.snps")} value={formatStat(stats?.snp_count)} icon={<Dna className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
                <StatCell label={t("home.indels")} value={formatStat(stats?.indel_count)} icon={<Dna className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
                <StatCell label={t("home.seedAccessions")} value={formatStat(stats?.seed_accessions)} icon={<Sprout className="size-3.5" aria-hidden />} loading={statsQuery.isLoading} />
              </dl>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <p>{t("home.statsSource")} · <span className="font-mono">Assembly Wm82.a4.v1</span></p>
              {stats?.last_release_date ? <p>Updated <span className="font-mono">{stats.last_release_date}</span></p> : null}
            </div>
          </>
        )}
      </section>

      <section className="border-y bg-muted/30 bg-gradient-accent">
        <div className="container-prose section-rhythm">
          <div className="mb-10"><p className="eyebrow">{t("home.dataOverview")}</p><h2 className="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">{t("home.dataOverviewDesc")}</h2></div>
          <div className="grid gap-6 lg:grid-cols-2 [&>*]:h-full">
            <Card className="scroll-fade-in flex h-full flex-col"><CardHeader><CardTitle>{t("home.chromosomeDistribution")}</CardTitle><CardDescription>{t("home.chromosomeDistributionDesc")}</CardDescription></CardHeader><CardContent className="flex-1">
              {densityQuery.isLoading ? <Skeleton className="h-72 w-full" /> : densityQuery.isError ? <DataErrorState message="Chromosome data unavailable." onRetry={() => void densityQuery.refetch()} /> : <React.Suspense fallback={<Skeleton className="h-72 w-full" />}><ChromosomeDensityChart data={density.map((d) => ({ chromosome: d.chromosome, variantCount: d.variant_count }))} /></React.Suspense>}
            </CardContent></Card>
            <Card className="scroll-fade-in flex h-full flex-col"><CardHeader><CardTitle>{t("home.impactDistribution")}</CardTitle><CardDescription>{t("home.impactDistributionDesc")}</CardDescription></CardHeader><CardContent className="flex-1">
              {impactQuery.isLoading ? <Skeleton className="h-64 w-full" /> : impactQuery.isError ? <DataErrorState message="Impact data unavailable." onRetry={() => void impactQuery.refetch()} /> : <React.Suspense fallback={<Skeleton className="h-64 w-full" />}><ImpactDistribution data={impactData} /></React.Suspense>}
            </CardContent></Card>
          </div>
        </div>
      </section>

      <section className="container-prose section-rhythm">
        <div className="mb-10 max-w-2xl"><p className="eyebrow">{t("home.featuresTitle")}</p><h2 className="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">{t("home.featuresSubtitle")}</h2></div>
        <div className="grid auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3 [&>*]:h-full">
          {FEATURES.map((feature) => { const Icon = feature.icon; return <Card key={feature.to} className="card-hover-accent group flex h-full flex-col transition-shadow hover:shadow-[var(--shadow-md)]"><CardContent className="flex flex-1 flex-col p-6"><div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent/70 text-accent-foreground transition-transform duration-300 group-hover:scale-105"><Icon className="size-5" aria-hidden /></div><h3 className="mt-4 font-display text-lg font-semibold">{t(feature.titleKey)}</h3><p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{t(feature.descKey)}</p><Link to={feature.to} className="link-underline mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary">{t("home.learnMore")}<ArrowRight className="size-3.5 transition-transform duration-300 group-hover:translate-x-0.5" aria-hidden /></Link></CardContent></Card>; })}
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

/** Compact stat cell for the hairline statistics strip. */
function StatCell({ label, value, icon, loading }: { label: string; value: string; icon: React.ReactNode; loading?: boolean }) {
  return (
    <div className="bg-card p-4 transition-colors hover:bg-muted/40 md:p-5">
      <dt className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        <span className="text-primary/70">{icon}</span>
        {label}
      </dt>
      <dd className={`mt-1.5 font-display text-xl font-semibold tabular-nums tracking-tight md:text-2xl ${loading ? "skeleton-pulse text-muted-foreground" : ""}`}>
        {value}
      </dd>
    </div>
  );
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

/** Locale-neutral example queries shown as suggestion chips under the hero search. */
const SEARCH_EXAMPLES: ReadonlyArray<string> = ["Glyma.01G001000", "Gm01:12345", "EMS mutant"];

/** Primary task entries on the homepage hero. */
const TASK_ENTRIES: ReadonlyArray<{
  to: string;
  titleKey: string;
  descKey: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Visual emphasis for the lead entry. */
  emphasis?: boolean;
  tileClass: string;
}> = [
  { to: "/genes", titleKey: "home.taskGenes", descKey: "genes.subtitle", icon: Layers, emphasis: true, tileClass: "bg-primary/10 text-primary" },
  { to: "/variants", titleKey: "home.taskVariants", descKey: "variants.subtitle", icon: Dna, tileClass: "bg-accent text-accent-foreground" },
  { to: "/blast", titleKey: "home.taskBlast", descKey: "blast.subtitle", icon: FlaskConical, tileClass: "bg-secondary text-secondary-foreground" },
];
