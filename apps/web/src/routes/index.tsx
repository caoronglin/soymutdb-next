/**
 * Public home page — PPTX V2 layout (top to bottom):
 *   1. Hero: title + subtitle + centered search + genome-assembly Select
 *      + three task entry cards
 *   2. Stats bar (real API statistics, visually de-emphasized)
 *   3. Scrolling photo area — featured news cover carousel
 *   4. Two-column content area (AntD Row/Col):
 *      - Left (md=8): latest news — up to 5 headlines as a link list
 *      - Right (md=16): editable welcome block (GET /site/home); when the
 *        welcome content is empty the right column hides and the news list
 *        takes the full md=24 width
 *
 * Motion (donghua): GSAP staggered hero entrance, CountUp stats, scroll
 * reveals below the fold — all gated on the app animation policy
 * (AnimationProvider: OS prefers-reduced-motion always wins, user "off"
 * switch respected). Lenis smooth scroll is mounted for "/" by
 * route-motion-runtime (see __root.tsx allowRouteMotion).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Search, Microscope, FlaskConical } from "lucide-react";
import { Button, Skeleton } from "@soymutdb/ui";
import { Card, Col, Empty, List, Row, Select, Tag } from "antd";
import DOMPurify from "dompurify";
import {
  fetchHomepageStats,
  getFeaturedNews,
  getSiteHome,
  type NewsSummary,
} from "@soymutdb/api-client";
import {
  CountUp,
  FadeUp,
  MotionProvider,
  gsap,
  type MotionConfig,
} from "@soymutdb/motion";
import { useAnimation } from "../lib/animation-context";
import { NewsCarousel, NEWS_FEATURED_KEY } from "../components/news-carousel";
import { pickNewsTitle } from "../components/news-card";
import { formatDate } from "../lib/format";
import { getAssemblies, type AssemblyInfo } from "./tools/api";

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  const anim = useAnimation();

  // Feed the app-level animation policy (intensity + reduced-motion) into the
  // motion primitives used on this page (CountUp / FadeUp read useMotion()).
  const motionConfig = React.useMemo<MotionConfig>(
    () => ({
      duration: anim.duration,
      durationFast: anim.durationFast,
      durationSlow: anim.durationSlow,
      easing: anim.easing,
      easingSpring: anim.easingSpring,
      stagger: anim.stagger,
      reduced: anim.reduced,
    }),
    [anim],
  );

  return (
    <MotionProvider config={motionConfig}>
      <HomeHero />
      <HomeStatsBar />
      <HomeNewsCarousel />
      <HomeDualSection />
    </MotionProvider>
  );
}

/* ---------------------------------------------------------------------------
 * 1. Hero — search + genome assembly + task entries
 * ------------------------------------------------------------------------- */

function HomeHero() {
  const { t } = useTranslation();
  const [searchValue, setSearchValue] = React.useState("");
  const [assembly, setAssembly] = React.useState<string | undefined>(undefined);
  const navigate = Route.useNavigate();
  const { reduced } = useAnimation();
  const heroRef = React.useRef<HTMLDivElement | null>(null);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];

  // Preselect the default assembly once the list arrives.
  React.useEffect(() => {
    if (assembly || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssembly(def.name);
  }, [assemblies, assembly]);

  // GSAP entrance — staggered fade-up of [data-hero-anim] nodes (~1.2s total).
  // Skipped entirely under reduced motion / animation "off" (content simply
  // renders visible). useLayoutEffect + fromTo avoids a visible flash.
  React.useLayoutEffect(() => {
    if (reduced) return;
    const root = heroRef.current;
    if (!root) return;
    const targets = root.querySelectorAll("[data-hero-anim]");
    if (targets.length === 0) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        targets,
        { autoAlpha: 0, y: 26 },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.7,
          ease: "power3.out",
          stagger: 0.1,
          overwrite: "auto",
          clearProps: "transform,opacity,visibility",
        },
      );
    }, root);
    return () => ctx.revert();
  }, [reduced]);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchValue.trim();
    if (!q) return;
    navigate({ to: "/search", search: { q, tissue: "", treatment: "", min_fpkm: undefined } });
  };

  return (
    <section className="border-b bg-gradient-accent">
      <div ref={heroRef} className="container-prose flex flex-col items-center py-20 text-center md:py-28">
        <h1 data-hero-anim className="mt-0 font-display text-4xl font-semibold leading-[1.1] tracking-tight md:text-5xl">
          <span className="block">{t("home.title")}</span>
          <span className="text-gradient block">{t("home.titleHighlight")}</span>
        </h1>
        <p data-hero-anim className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground md:text-lg">
          {t("home.subtitle")}
        </p>

        <form data-hero-anim onSubmit={onSearch} className="mt-8 w-full max-w-2xl" role="search">
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
            <Button
              type="submit"
              size="lg"
              className="absolute right-1.5 top-1 h-12 transition-transform hover:brightness-110 active:scale-[0.97]"
            >
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
                className="inline-flex h-11 items-center rounded-full border border-border bg-card px-4 text-xs text-muted-foreground transition-all hover:-translate-y-px hover:border-primary/40 hover:text-primary"
              >
                {example}
              </button>
            ))}
          </div>
        </form>

        {/* Genome assembly selector — hidden when the API returns no data. */}
        {assemblies.length > 0 ? (
          <div
            className="mt-5 flex flex-wrap items-center justify-center gap-2 text-sm"
            style={{ animation: "fadeInUp 500ms cubic-bezier(0.16,1,0.3,1) both" }}
          >
            <span className="text-muted-foreground">{t("home.assembly")}</span>
            <Select
              aria-label={t("home.assembly")}
              size="small"
              className="min-w-52"
              value={assembly}
              onChange={(value: string) => setAssembly(value)}
              options={assemblies.map((a: AssemblyInfo) => ({
                value: a.name,
                label: a.species ? `${a.name} · ${a.species}` : a.name,
              }))}
            />
          </div>
        ) : null}

        {/* Task entries — the three primary jobs */}
        <div className="mt-10 grid w-full max-w-4xl gap-3 sm:grid-cols-3">
          {TASK_ENTRIES.map((entry) => {
            const Icon = entry.icon;
            return (
              <Link
                key={entry.to}
                to={entry.to}
                data-hero-anim
                className="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <Card
                  className="h-full transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-0.5 group-hover:shadow-md"
                  styles={{ body: { padding: "1rem" } }}
                >
                  <span className="flex items-start gap-3 text-left">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary transition-colors duration-300 group-hover:bg-primary/10">
                      <Icon className="size-5" aria-hidden />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold tracking-tight transition-colors group-hover:text-primary">
                        {t(entry.titleKey)}
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                        {t(entry.descKey)}
                      </span>
                    </span>
                  </span>
                </Card>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * 2. Stats bar — real API statistics, de-emphasized under the hero
 * ------------------------------------------------------------------------- */

function HomeStatsBar() {
  const { t } = useTranslation();

  const statsQuery = useQuery({
    queryKey: ["homepage-stats"],
    queryFn: fetchHomepageStats,
    staleTime: 10 * 60 * 1000,
  });

  const stats = statsQuery.data;

  const items: ReadonlyArray<{ labelKey: string; value: number | null | undefined }> = [
    { labelKey: "home.totalVariants", value: stats?.total_variants },
    { labelKey: "home.genes", value: stats?.gene_count },
    { labelKey: "home.mutantLines", value: stats?.mutant_line_count },
    { labelKey: "home.snps", value: stats?.snp_count },
    { labelKey: "home.indels", value: stats?.indel_count },
    { labelKey: "home.seedAccessions", value: stats?.seed_accessions },
  ];

  return (
    <section className="border-b bg-muted/10" aria-label={t("home.statsTitle")}>
      <div className="container-prose py-4">
        {statsQuery.isError ? (
          <p className="text-center text-xs text-muted-foreground">
            {t("home.statsUnavailable")}
            <button
              type="button"
              onClick={() => void statsQuery.refetch()}
              className="ml-2 text-primary underline-offset-2 hover:underline"
            >
              {t("common.retry")}
            </button>
          </p>
        ) : (
          <>
            <dl className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2">
              {items.map((item) => (
                <div key={item.labelKey} className="flex items-baseline gap-2">
                  <dt className="text-[11px] uppercase tracking-wider text-muted-foreground/80">
                    {t(item.labelKey)}
                  </dt>
                  <dd className="font-display text-base font-semibold tabular-nums">
                    {statsQuery.isLoading ? (
                      <Skeleton className="h-4 w-14" />
                    ) : item.value == null ? (
                      "—"
                    ) : (
                      <CountUp end={item.value} duration={1000} className="font-display" />
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-center text-[11px] text-muted-foreground/70">
              {t("home.statsSource")} · <span className="font-mono">Wm82.a4.v1</span>
              {stats?.last_release_name ? <> · {stats.last_release_name}</> : null}
              {stats?.last_release_date ? (
                <>
                  {" "}
                  · Updated <span className="font-mono">{stats.last_release_date}</span>
                </>
              ) : null}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * 3. Carousel — scrolling photo area (featured news covers)
 * ------------------------------------------------------------------------- */

function HomeNewsCarousel() {
  const { t } = useTranslation();

  return (
    <section className="border-b bg-card/40" aria-label={t("news.title")}>
      <div className="container-prose py-10">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">{t("news.title")}</p>
            <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
              {t("news.latestNews")}
            </h2>
          </div>
          <Link
            to="/news"
            search={{ category: undefined, page: undefined }}
            className="link-underline inline-flex items-center gap-1 text-sm font-medium text-primary"
          >
            {t("news.viewAll")}
          </Link>
        </div>

        {/* Scrolling photo area — featured news covers */}
        <FadeUp>
          <NewsCarousel />
        </FadeUp>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * 4. Two-column content area — latest news (left) + editable welcome (right)
 * ------------------------------------------------------------------------- */

function HomeDualSection() {
  const { t, i18n } = useTranslation();

  const featuredQuery = useQuery({
    queryKey: NEWS_FEATURED_KEY,
    queryFn: getFeaturedNews,
    staleTime: 5 * 60 * 1000,
  });
  const featured = (featuredQuery.data?.featured ?? []).slice(0, 5);

  const homeQuery = useQuery({
    queryKey: ["site-home"],
    queryFn: getSiteHome,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const data = homeQuery.data;
  const isZh = i18n.language.toLowerCase().startsWith("zh");
  const html = data ? (isZh && data.welcome_zh ? data.welcome_zh : data.welcome_en) : null;
  // Loading / error / empty all hide the welcome column — the home page
  // degrades gracefully and never shows fake or broken content. When hidden,
  // the news list expands to the full md=24 column width.
  const hasWelcome = Boolean(html?.trim());

  return (
    <FadeUp>
      <section className="border-b bg-background" aria-label={t("news.title")}>
        <div className="container-prose py-12">
          <Row gutter={[24, 24]}>
            <Col xs={24} md={hasWelcome ? 8 : 24}>
              {/* Latest headlines — up to 5 linked titles (PPTX) */}
              {featuredQuery.isLoading ? (
                <div className="space-y-2" data-testid="home-news-loading">
                  {Array.from({ length: 5 }, (_, i) => (
                    <div key={i} className="h-12 rounded-lg border border-border bg-muted/30" />
                  ))}
                </div>
              ) : featuredQuery.isError ? (
                <div className="rounded-xl border border-border bg-card py-10">
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("news.homeUnavailable")}
                  />
                </div>
              ) : featured.length === 0 ? (
                <div className="rounded-xl border border-border bg-card py-10">
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("news.noNews")}
                  />
                </div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-border bg-card">
                  <List
                    itemLayout="horizontal"
                    dataSource={featured}
                    renderItem={(item: NewsSummary) => {
                      const title = pickNewsTitle(item, i18n.language);
                      return (
                        <List.Item key={item.slug} className="!px-0 transition-colors hover:bg-accent/50">
                          <Link
                            to="/news/$slug"
                            params={{ slug: item.slug }}
                            aria-label={title}
                            className="flex w-full items-center gap-3 px-4 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {item.category ? (
                              <Tag color="green" className="m-0 shrink-0">
                                {t(`news.categories.${item.category}`, {
                                  defaultValue: item.category,
                                })}
                              </Tag>
                            ) : (
                              <span className="w-0 shrink-0" aria-hidden />
                            )}
                            <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                              {title}
                            </span>
                            {item.published_at ? (
                              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                                {formatDate(item.published_at)}
                              </span>
                            ) : null}
                          </Link>
                        </List.Item>
                      );
                    }}
                  />
                </div>
              )}
            </Col>

            {/* Editable welcome block — GET /site/home, admin-authored HTML */}
            {hasWelcome ? (
              <Col xs={24} md={16}>
                <p className="eyebrow">{t("home.welcome")}</p>
                <div
                  data-testid="home-welcome"
                  className="news-content prose-sm mt-4 text-base leading-relaxed text-foreground/90"
                  // Admin-authored HTML, bleach-sanitised by the backend on
                  // read; DOMPurify re-sanitises as defence in depth.
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html ?? "") }}
                />
              </Col>
            ) : null}
          </Row>
        </div>
      </section>
    </FadeUp>
  );
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
