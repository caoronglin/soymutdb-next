/** Public home page. All displayed statistics come from the API. */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Search, Microscope, FlaskConical } from "lucide-react";
import { Button, Skeleton } from "@soymutdb/ui";
import { fetchHomepageStats } from "@soymutdb/api-client";

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  const { t } = useTranslation();
  const [searchValue, setSearchValue] = React.useState("");
  const navigate = Route.useNavigate();

  const statsQuery = useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
    staleTime: 10 * 60 * 1000,
  });

  const stats = statsQuery.data;

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchValue.trim();
    if (!q) return;
    navigate({ to: "/search", search: { q, tissue: "", treatment: "", min_fpkm: undefined } });
  };

  return (
    <>
      <section className="border-b bg-gradient-accent">
        <div className="container-prose flex flex-col items-center py-20 text-center md:py-28">
          <h1 className="mt-0 font-display text-4xl font-semibold leading-[1.1] tracking-tight md:text-5xl">
            <span className="block">{t("home.title")}</span>
            <span className="text-gradient block">{t("home.titleHighlight")}</span>
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground md:text-lg">{t("home.subtitle")}</p>
          <form onSubmit={onSearch} className="mt-8 w-full max-w-2xl" role="search">
            <div className="relative">
              <Search className="pointer-events-none absolute left-5 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                type="search"
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                placeholder={t("home.searchPlaceholder")}
                aria-label={t("nav.search")}
                className="h-14 w-full rounded-xl border border-input bg-card pl-12 pr-32 text-base shadow-sm outline-none transition-colors placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
              <Button type="submit" size="lg" className="absolute right-1.5 top-1 h-12">
                {t("home.search")}
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
              {SEARCH_EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() =>
                    navigate({ to: "/search", search: { q: example, tissue: "", treatment: "", min_fpkm: undefined } })
                  }
                  className="rounded-full border border-border bg-card px-3 py-1 font-mono text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                >
                  {example}
                </button>
              ))}
            </div>
          </form>

          {/* Task entries — the three primary jobs */}
          <div className="mt-10 grid w-full max-w-3xl gap-3 sm:grid-cols-3">
            {TASK_ENTRIES.map((entry) => {
              const Icon = entry.icon;
              return (
                <Link
                  key={entry.to}
                  to={entry.to}
                  className="group flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold tracking-tight">{t(entry.titleKey)}</span>
                    <span className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{t(entry.descKey)}</span>
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      <section className="border-b bg-muted/20">
        <div className="container-prose py-6">
          {statsQuery.isError ? (
            <DataErrorState message="Database statistics unavailable." onRetry={() => void statsQuery.refetch()} />
          ) : (
            <>
              <dl className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.totalVariants")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.total_variants)}</dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.genes")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.gene_count)}</dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.mutantLines")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.mutant_line_count)}</dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.snps")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.snp_count)}</dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.indels")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.indel_count)}</dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">{t("home.seedAccessions")}</dt>
                  <dd className="font-display text-lg font-semibold tabular-nums">{statsQuery.isLoading ? <Skeleton className="h-5 w-16" /> : formatStat(stats?.seed_accessions)}</dd>
                </div>
              </dl>
              <p className="mt-4 text-center text-xs text-muted-foreground">
                {t("home.statsSource")} · <span className="font-mono">Wm82.a4.v1</span>
                {stats?.last_release_name ? <> · {stats.last_release_name}</> : null}
                {stats?.last_release_date ? <> · Updated <span className="font-mono">{stats.last_release_date}</span></> : null}
              </p>
            </>
          )}
        </div>
      </section>
    </>
  );
}

function formatStat(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString();
}

function DataErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"><p className="text-sm text-destructive">{message}</p><Button type="button" variant="outline" size="sm" onClick={onRetry}>Retry</Button></div>;
}

/** Locale-neutral example queries shown as suggestion chips under the hero search. */
const SEARCH_EXAMPLES: ReadonlyArray<string> = ["Glyma.01G001000", "Gm01:12345", "EMS mutant"];

/** Primary task entries on the homepage hero. */
const TASK_ENTRIES: ReadonlyArray<{
  to: string;
  titleKey: string;
  descKey: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { to: "/browser", titleKey: "nav.browser", descKey: "browser.subtitle", icon: Microscope },
  { to: "/blast", titleKey: "nav.blast", descKey: "blast.subtitle", icon: FlaskConical },
  { to: "/genes", titleKey: "home.taskGenes", descKey: "genes.subtitle", icon: Search },
];
