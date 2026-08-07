/**
 * Search route — global search across genes, variants, mutant lines,
 * documentation, and expression data. Supports advanced filters for
 * expression queries.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
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

export const Route = createFileRoute("/search")({
  component: SearchComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    q: String(search.q ?? ""),
    tissue: search.tissue ? String(search.tissue) : "",
    treatment: search.treatment ? String(search.treatment) : "",
    min_fpkm: search.min_fpkm ? Number(search.min_fpkm) : undefined,
  }),
});

function SearchComponent() {
  const { t } = useTranslation();
  const { q, tissue, treatment, min_fpkm } = Route.useSearch();
  const navigate = useNavigate();
  const [input, setInput] = React.useState(q);
  const [showFilters, setShowFilters] = React.useState(
    Boolean(tissue || treatment || min_fpkm),
  );

  // Local filter state
  const [filterTissue, setFilterTissue] = React.useState(tissue ?? "");
  const [filterTreatment, setFilterTreatment] = React.useState(treatment ?? "");
  const [filterMinFpkm, setFilterMinFpkm] = React.useState(
    min_fpkm != null ? String(min_fpkm) : "",
  );

  React.useEffect(() => setInput(q), [q]);
  React.useEffect(() => {
    setFilterTissue(tissue ?? "");
    setFilterTreatment(treatment ?? "");
    setFilterMinFpkm(min_fpkm != null ? String(min_fpkm) : "");
  }, [tissue, treatment, min_fpkm]);

  const hasExpressionFilters = Boolean(
    filterTissue || filterTreatment || filterMinFpkm,
  );

  const searchQuery = useQuery({
    queryKey: ["global-search", q],
    queryFn: () => globalSearch({ q, page: 1, page_size: 20 }),
    enabled: q.length > 0,
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
        gene_id: q,
        tissue: filterTissue || undefined,
        treatment: filterTreatment || undefined,
        min_fpkm: filterMinFpkm ? Number(filterMinFpkm) : undefined,
        page: 1,
        page_size: 10,
      }),
    enabled: q.length > 0 && hasExpressionFilters,
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
    </div>
  );
}
