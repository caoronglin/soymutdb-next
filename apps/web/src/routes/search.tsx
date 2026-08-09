/**
 * Search route — global search across genes, variants, mutant lines,
 * documentation, and expression data. Supports advanced filters for
 * expression queries.
 *
 * The route doubles as the portal shell for the six second-level search
 * catalogs (Gene ID / Physical Location / Gbrowse / Primer Design / BLAST /
 * Search Tools, per the PPTX V2 design): the global search box lives at the
 * top, an AntD tab bar switches between the nested child routes, and
 * `/search` redirects to `/search/genes` (the default catalog).
 */
import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  Search as SearchIcon,
  Dna,
  Beaker,
  FileText,
  BarChart3,
  ArrowRight,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import {
  Card,
  CardContent,
  EmptyState,
  Skeleton,
  Badge,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Label,
} from "@soymutdb/ui";
import { Card as AntdCard, Col, Row, Tabs } from "antd";
import {
  EnvironmentOutlined,
  ExperimentOutlined,
  GlobalOutlined,
  IdcardOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { globalSearch, searchExpression } from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";

const TISSUE_OPTIONS = [
  { value: "leaf", label: "Leaf" },
  { value: "root", label: "Root" },
  { value: "seed", label: "Seed" },
  { value: "nodule", label: "Nodule" },
  { value: "flower", label: "Flower" },
  { value: "pod", label: "Pod" },
  { value: "stem", label: "Stem" },
  { value: "cotyledon", label: "Cotyledon" },
  { value: "shoot_apex", label: "Shoot Apex" },
];

const TREATMENT_OPTIONS = [
  { value: "control", label: "Control" },
  { value: "drought", label: "Drought" },
  { value: "salt", label: "Salt" },
  { value: "cold", label: "Cold" },
  { value: "heat", label: "Heat" },
  { value: "flooding", label: "Flooding" },
  { value: "pathogen", label: "Pathogen" },
  { value: "nutrient_deficiency", label: "Nutrient Deficiency" },
];

/** Second-level search catalogs (PPTX order), wired to the nested routes. */
const SEARCH_TABS = [
  { to: "/search/genes", labelKey: "search.tabGenes" },
  { to: "/search/location", labelKey: "search.tabLocation" },
  { to: "/search/gbrowse", labelKey: "search.tabGbrowse" },
  { to: "/search/primer", labelKey: "search.tabPrimer" },
  { to: "/search/blast", labelKey: "search.tabBlast" },
  { to: "/search/tools", labelKey: "search.tabTools" },
] as const;

/**
 * Search hub entry grid (PPTX V2 slide 2) — all six second-level catalogs
 * as clickable cards with semantic icons. Titles reuse the tab keys;
 * descriptions reuse the per-catalog subtitle/desc keys.
 */
const SEARCH_HUB: ReadonlyArray<{
  to: (typeof SEARCH_TABS)[number]["to"];
  titleKey: string;
  descKey: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { to: "/search/genes", titleKey: "search.tabGenes", descKey: "search.genes.subtitle", icon: IdcardOutlined },
  { to: "/search/location", titleKey: "search.tabLocation", descKey: "search.location.subtitle", icon: EnvironmentOutlined },
  { to: "/search/gbrowse", titleKey: "search.tabGbrowse", descKey: "search.gbrowse.subtitle", icon: GlobalOutlined },
  { to: "/search/primer", titleKey: "search.tabPrimer", descKey: "search.primer.desc", icon: ExperimentOutlined },
  { to: "/search/blast", titleKey: "search.tabBlast", descKey: "search.blast.desc", icon: ThunderboltOutlined },
  { to: "/search/tools", titleKey: "search.tabTools", descKey: "search.tools.desc", icon: ToolOutlined },
];

export const Route = createFileRoute("/search")({
  component: SearchComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    q: search.q ? String(search.q) : undefined,
    tissue: search.tissue ? String(search.tissue) : undefined,
    treatment: search.treatment ? String(search.treatment) : undefined,
    min_fpkm: search.min_fpkm ? Number(search.min_fpkm) : undefined,
  }),
});

function SearchComponent() {
  const { t } = useTranslation();
  const { q, tissue, treatment, min_fpkm } = Route.useSearch();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [input, setInput] = React.useState(q ?? "");
  const [showFilters, setShowFilters] = React.useState(
    Boolean(tissue || treatment || min_fpkm),
  );

  // Local filter state
  const [filterTissue, setFilterTissue] = React.useState(tissue ?? "");
  const [filterTreatment, setFilterTreatment] = React.useState(treatment ?? "");
  const [filterMinFpkm, setFilterMinFpkm] = React.useState(
    min_fpkm != null ? String(min_fpkm) : "",
  );

  React.useEffect(() => setInput(q ?? ""), [q]);
  React.useEffect(() => {
    setFilterTissue(tissue ?? "");
    setFilterTreatment(treatment ?? "");
    setFilterMinFpkm(min_fpkm != null ? String(min_fpkm) : "");
  }, [tissue, treatment, min_fpkm]);

  // `/search` renders the shell with the default catalog — forward to
  // `/search/genes`, keeping the current search params in the URL.
  React.useEffect(() => {
    if (pathname === "/search" || pathname === "/search/") {
      navigate({
        to: "/search/genes",
        replace: true,
        search: { q, tissue, treatment, min_fpkm },
      });
    }
  }, [pathname, q, tissue, treatment, min_fpkm, navigate]);

  const hasExpressionFilters = Boolean(
    filterTissue || filterTreatment || filterMinFpkm,
  );

  const searchQuery = useQuery({
    queryKey: ["global-search", q ?? ""],
    queryFn: () => globalSearch({ q: q ?? "", page: 1, page_size: 20 }),
    enabled: Boolean(q && q.trim()),
    staleTime: 60_000,
  });

  const expressionQuery = useQuery({
    queryKey: [
      "expression-search",
      q,
      filterTissue,
      filterTreatment,
      filterMinFpkm,
    ],
    queryFn: () =>
      searchExpression({
        gene_id: q ?? "",
        tissue: filterTissue || undefined,
        treatment: filterTreatment || undefined,
        min_fpkm: filterMinFpkm ? Number(filterMinFpkm) : undefined,
        page: 1,
        page_size: 10,
      }),
    enabled: Boolean(q && q.trim()) && hasExpressionFilters,
    staleTime: 60_000,
  });

  const results = searchQuery.data?.results ?? [];
  const byType = searchQuery.data?.by_type;
  const expressionResults = expressionQuery.data?.items ?? [];

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = input.trim();
    if (!next) return;
    navigate({
      to: "/search",
      search: {
        q: next,
        tissue: filterTissue,
        treatment: filterTreatment,
        min_fpkm: filterMinFpkm ? Number(filterMinFpkm) : undefined,
      },
    });
  };

  const activeTab =
    SEARCH_TABS.find((tab) => pathname.startsWith(tab.to))?.to ??
    "/search/genes";

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("search.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {t("search.subtitle")}
        </h1>
      </FadeUp>

      <form onSubmit={applyFilters} className="mt-10" role="search">
        <div className="relative">
          <SearchIcon
            className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("search.placeholder")}
            aria-label={t("search.title")}
            className="h-12 pl-12"
            autoFocus
          />
        </div>

        {/* Advanced Filters Toggle */}
        <button
          type="button"
          onClick={() => setShowFilters(!showFilters)}
          className="mt-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          {showFilters ? (
            <ChevronUp className="size-4" aria-hidden />
          ) : (
            <ChevronDown className="size-4" aria-hidden />
          )}
          {t("search.advanced_filters")}
        </button>

        {showFilters ? (
          <div className="mt-3 grid gap-3 rounded-lg border p-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="filter-tissue">{t("genes.expression.tissue")}</Label>
              <Select
                value={filterTissue}
                onValueChange={(v) => setFilterTissue(v === "all" ? "" : v)}
              >
                <SelectTrigger id="filter-tissue">
                  <SelectValue placeholder="All tissues" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  {TISSUE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="filter-treatment">
                {t("genes.expression.treatment")}
              </Label>
              <Select
                value={filterTreatment}
                onValueChange={(v) => setFilterTreatment(v === "all" ? "" : v)}
              >
                <SelectTrigger id="filter-treatment">
                  <SelectValue placeholder="All treatments" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  {TREATMENT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="filter-min-fpkm">{t("search.min_fpkm")}</Label>
              <Input
                id="filter-min-fpkm"
                type="number"
                min={0}
                step={0.1}
                value={filterMinFpkm}
                onChange={(e) => setFilterMinFpkm(e.target.value)}
                placeholder="e.g., 1.0"
              />
            </div>
          </div>
        ) : null}
      </form>

      {q ? (
        <p className="mt-6 text-sm text-muted-foreground">
          {t("search.resultsFor")}{" "}
          <span className="font-mono text-foreground">"{q}"</span>
          {byType
            ? ` · ${searchQuery.data?.total ?? 0} results`
            : null}
        </p>
      ) : null}

      <div className="mt-10 space-y-6">
        {/* Global Search Results */}
        {searchQuery.isLoading ? (
          <div className="grid gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : results.length === 0 && q && !hasExpressionFilters ? (
          <EmptyState
            icon={SearchIcon}
            title={t("search.noResults")}
            description={t("common.noResults")}
          />
        ) : results.length > 0 ? (
          <div className="grid gap-3">
            {results.map((r) => {
              const Icon =
                r.type === "gene"
                  ? Dna
                  : r.type === "variant"
                    ? Dna
                    : r.type === "mutant_line"
                      ? Beaker
                      : r.type === "expression"
                        ? BarChart3
                        : FileText;
              return (
                <Card key={`${r.type}-${r.id}`} className="card-lift">
                  <CardContent className="flex items-center gap-4">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                      <Icon className="size-5" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="secondary"
                          className="font-mono text-[10px] uppercase"
                        >
                          {r.type}
                        </Badge>
                        <p className="truncate font-medium">{r.name}</p>
                      </div>
                      {r.description ? (
                        <p className="mt-1 truncate text-sm text-muted-foreground">
                          {r.description}
                        </p>
                      ) : null}
                    </div>
                    <Link
                      to={r.url ?? "#"}
                      className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      aria-label={`View ${r.name}`}
                    >
                      <ArrowRight className="size-4" aria-hidden />
                    </Link>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : null}

        {/* Expression Search Results */}
        {hasExpressionFilters && expressionQuery.isLoading ? (
          <div className="grid gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={`expr-skel-${i}`} className="h-20 w-full" />
            ))}
          </div>
        ) : expressionResults.length > 0 ? (
          <div className="grid gap-3">
            <p className="text-sm font-medium text-muted-foreground">
              Expression results ({expressionResults.length})
            </p>
            {expressionResults.map((item: unknown, idx: number) => {
              const record = item as {
                gene_id?: string;
                library_name?: string;
                fpkm?: number;
                tpm?: number;
                tissue?: string;
                treatment?: string;
              };
              return (
                <Card key={`expr-${idx}`} className="card-lift">
                  <CardContent className="flex items-center gap-4">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                      <BarChart3 className="size-5" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="secondary"
                          className="font-mono text-[10px] uppercase"
                        >
                          expression
                        </Badge>
                        <p className="truncate font-medium font-mono text-sm">
                          {record.gene_id ?? "—"}
                        </p>
                      </div>
                      <p className="mt-1 truncate text-sm text-muted-foreground">
                        {record.library_name ?? "—"} ·{" "}
                        {record.tissue ?? "—"} ·{" "}
                        {record.treatment ?? "—"} ·{" "}
                        <span className="font-mono">
                          FPKM: {record.fpkm?.toFixed(2) ?? "—"}
                        </span>
                      </p>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : null}
      </div>

      {/* Second-level catalog navigation (PPTX V2) */}
      <Tabs
        className="mt-10"
        activeKey={activeTab}
        onChange={(key) =>
          navigate({
            to: key as (typeof SEARCH_TABS)[number]["to"],
            search: { q, tissue, treatment, min_fpkm },
          })
        }
        items={SEARCH_TABS.map((tab) => ({
          key: tab.to,
          label: t(tab.labelKey),
        }))}
      />

      {/* Search hub — entry cards for the six second-level catalogs (PPTX V2) */}
      <div className="mt-10">
        <p className="eyebrow">{t("search.hub.title")}</p>
        <Row gutter={[16, 16]} className="mt-3">
          {SEARCH_HUB.map((entry) => {
            const Icon = entry.icon;
            return (
              <Col key={entry.to} xs={12} md={8}>
                <Link
                  to={entry.to}
                  search={{ q, tissue, treatment, min_fpkm }}
                  className="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <AntdCard
                    hoverable
                    className="h-full transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-0.5 group-hover:shadow-md"
                    styles={{ body: { padding: "1rem" } }}
                  >
                    <span className="flex items-start gap-3 text-left">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary transition-colors duration-300 group-hover:bg-primary/10">
                        <Icon className="text-lg" aria-hidden />
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
                  </AntdCard>
                </Link>
              </Col>
            );
          })}
        </Row>
      </div>

      <div className="pb-10">
        <Outlet />
      </div>
    </div>
  );
}
