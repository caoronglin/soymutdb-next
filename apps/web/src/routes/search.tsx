import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowRightOutlined as ArrowRight,
  DeploymentUnitOutlined as Dna,
  ExperimentOutlined as Beaker,
  FileTextOutlined as FileText,
  SearchOutlined as SearchIcon,
} from "@ant-design/icons";
import { Button, Card, Empty, Input, Skeleton, Tag } from "@/lib/antd";
import {
  getReleaseId,
  globalSearch,
  internalSearch,
  type InternalSearchResponse,
  type SearchResponse,
  type SearchResult,
  type SearchResultType,
} from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { queryKeys } from "../lib/query-keys";
import { SITE_VARIANT } from "../lib/site-variant";

/** Result types the API accepts; unknown `?types=` values are ignored. */
const SEARCH_RESULT_TYPES: readonly SearchResultType[] = [
  "gene",
  "variant",
  "mutant_line",
  "phenotype",
  "publication",
] as const;

/**
 * URL search contract of /search. Declared explicitly (instead of casting the
 * validator to `any`) so a typo in a parameter name, or a new key that the
 * component never reads, fails the typecheck rather than silently producing an
 * untyped search object.
 */
export interface SearchRouteParams {
  q?: string;
  types?: string[];
  cursor?: string;
  limit?: number;
  assembly?: string;
}

export const Route = createFileRoute("/search")({
  component: SearchComponent,
  validateSearch: (search: Record<string, unknown>): SearchRouteParams => ({
    q: search.q ? String(search.q) : undefined,
    types: Array.isArray(search.types) ? search.types.map(String) : undefined,
    cursor: search.cursor ? String(search.cursor) : undefined,
    limit: search.limit ? Number(search.limit) : undefined,
    assembly: search.assembly ? String(search.assembly) : undefined,
  }),
});

function isCatalogSearch(data: SearchResponse | InternalSearchResponse): data is SearchResponse {
  return "results" in data;
}

function isInternalDirectory(data: SearchResponse | InternalSearchResponse): data is InternalSearchResponse {
  return "mutants" in data || "genes" in data;
}

function normalizeInternalResults(data: InternalSearchResponse): SearchResult[] {
  const genes: SearchResult[] = (data.genes ?? []).map((item) => ({
    type: "gene",
    id: item.gene_id,
    public_id: item.gene_id,
    internal_id: item.internal_id,
    name: item.name ?? item.gene_id,
    description: `${item.matched_field} · ${item.match_type}`,
    url: item.url ?? undefined,
    source: "internal",
    release_id: item.release_id,
    assembly_id: item.assembly_id,
    match_type: item.match_type,
  }));
  const mutants: SearchResult[] = (data.mutants ?? []).map((item) => ({
    type: "mutant_line",
    id: item.public_id,
    public_id: item.public_id,
    internal_id: item.internal_id,
    name: item.name,
    description: `${item.matched_field} · ${item.match_type}`,
    url: item.url ?? undefined,
    source: "internal",
    release_id: item.release_id,
    match_type: item.match_type,
  }));
  return [...genes, ...mutants];
}

const RESULT_ICONS: Record<string, typeof Dna> = {
  gene: Dna,
  variant: Dna,
  mutant_line: Beaker,
};

function SearchComponent() {
  const { t } = useTranslation();
  const { q, types, cursor, limit, assembly } = Route.useSearch();
  // URL values are free-form strings; only the known result types may be sent.
  const selectedTypes = React.useMemo<SearchResultType[] | undefined>(() => {
    if (!types || types.length === 0) return undefined;
    const known = types.filter((value): value is SearchResultType =>
      (SEARCH_RESULT_TYPES as readonly string[]).includes(value),
    );
    return known.length > 0 ? known : undefined;
  }, [types]);
  const navigate = useNavigate();
  const [input, setInput] = React.useState(q ?? "");

  React.useEffect(() => setInput(q ?? ""), [q]);

  const releaseId = getReleaseId();
  const internalSite = SITE_VARIANT === "internal";
  const resultLimit = limit ?? 20;
  const releaseNumber = releaseId && /^\d+$/.test(releaseId) ? Number(releaseId) : undefined;
  // Federated (external-source) search is retired permanently: the portal only
  // ever queries its own catalogue or the internal directory.
  const query = useQuery<SearchResponse | InternalSearchResponse>({
    queryKey: queryKeys.search.global({
      query: q,
      // The narrowed selection keys the cache, so an all-unknown `?types=`
      // URL cannot reuse the unfiltered entry.
      types: selectedTypes,
      cursor,
      limit: resultLimit,
      assemblyId: assembly,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      internalSite
        ? internalSearch(q!, { limit: resultLimit })
        : globalSearch({
            q: q!,
            types: selectedTypes,
            cursor,
            limit: resultLimit,
            assembly_id: assembly ? Number(assembly) : undefined,
            release_id: releaseNumber,
          }),
    enabled: Boolean(q?.trim()),
    staleTime: 60_000,
  });

  const runSearch = (raw: string) => {
    const next = raw.trim();
    void navigate({ to: "/search", search: {
      q: next || undefined, types: undefined, cursor: undefined,
      assembly: undefined, limit: next ? 20 : undefined,
    } });
  };

  // `/search` is the portal search page; every route beneath it (`/search/genes`,
  // `/search/location`, `/search/blast`, …) is a standalone tool page with its own
  // heading, form and result table. Rendering the portal hero and the global search
  // box for those children contradicts the approved reference structure and pushes
  // each tool's own form below a full screen of unrelated content.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isPortalSearchPage = pathname === "/search" || pathname === "/search/";
  if (!isPortalSearchPage) {
    return (
      <div className="container-prose section-rhythm">
        <Outlet />
      </div>
    );
  }

  const data = query.data;
  const catalog = data && isCatalogSearch(data) ? data : undefined;
  const directory = data && isInternalDirectory(data) ? data : undefined;
  const results = catalog?.results ?? (directory ? normalizeInternalResults(directory) : []);
  const totalCount = catalog?.total_count ?? directory?.total_count ?? null;
  const isRefreshing = Boolean(data) && query.isFetching;

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("nav.search")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("search.heroTitle")}</h1>
        <p className="mt-3 max-w-2xl text-muted-foreground">{t("search.portalDescription")}</p>
      </FadeUp>

      {/* antd's native search input: the built-in enter button replaces the
          hand-rolled form + button pair, and the retired external-source
          toggle no longer sits under it. */}
      <div className="mt-10" role="search">
        <Input.Search
          size="large"
          allowClear
          enterButton
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onSearch={runSearch}
          placeholder={t("search.portalPlaceholder")}
          aria-label={t("common.search")}
          data-testid="search-portal-input"
        />
      </div>

      {!q ? <div className="mt-12"><Empty image={<SearchIcon style={{ fontSize: 40, color: "var(--muted-foreground)" }} />} description={<><p className="font-medium">{t("search.emptyPromptTitle")}</p><p className="text-sm text-muted-foreground">{t("search.emptyPromptDescription")}</p></>} /></div> : null}
      {q && query.isError ? <Card className="mt-10 border-destructive/40"><div className="flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="font-medium">{t("search.errorTitle")}</p><p className="text-sm text-muted-foreground">{t("common.requestId")}: {(query.error as { request_id?: string })?.request_id ?? t("common.notAvailable")}</p></div><Button onClick={() => void query.refetch()}>{t("common.retry")}</Button></div></Card> : null}
      {q && query.isLoading && !data ? <div data-testid="search-results" className="mt-10 grid gap-3">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-20 w-full" />)}</div> : null}

      {(catalog || directory) ? <section data-testid="search-results" className="mt-10" aria-label={t("search.resultsAria")}>
        <div className="mb-4 flex items-center justify-between text-sm text-muted-foreground"><span>{t("search.resultsFor")} <span className="font-mono text-foreground">“{q}”</span>{isRefreshing ? <span> · {t("search.refreshing")}</span> : null}</span>{totalCount !== null ? <span>{t("search.resultCount", { count: totalCount })}</span> : null}</div>
        {results.length === 0 ? <Empty image={<SearchIcon style={{ fontSize: 40, color: "var(--muted-foreground)" }} />} description={<><p className="font-medium">{t("search.noResults")}</p><p className="text-sm text-muted-foreground">{t("search.noMatchesDescription")}</p></>} /> : <div className="grid gap-3">{results.map((result) => <ResultRow key={`${result.type}-${result.id}-${result.internal_id ?? "public"}`} result={result} />)}</div>}
      </section> : null}

      <div className="mt-14 pb-10"><Outlet /></div>
    </div>
  );
}

function CopyIdentifier({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <Button size="small" onClick={() => void copy()}>
      {copied ? t("common.copied") : t("common.copy")}
    </Button>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  const { t } = useTranslation();
  const Icon = RESULT_ICONS[result.type] ?? FileText;
  const publicId = result.public_id ?? result.id;
  const context = [
    result.assembly,
    result.release_id != null ? `${t("search.releaseLabel")} ${result.release_id}` : undefined,
    result.match_type,
    result.source,
  ].filter(Boolean).join(" · ");
  const content = (
    <Card
      data-testid={result.url ? "search-result-row" : "search-result-disabled"}
      data-url={result.url ?? undefined}
      data-public-id={publicId}
      className={!result.url ? "opacity-60" : "card-lift"}
      aria-disabled={!result.url}
    >
      <div className="flex items-center gap-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Icon className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Tag className="font-mono text-[10px] uppercase">{result.type}</Tag>
            <p className="truncate font-medium">{result.name ?? publicId}</p>
            <code className="font-mono text-xs text-muted-foreground">{publicId}</code>
            {SITE_VARIANT === "internal" && result.internal_id ? (
              <span className="flex items-center gap-1" data-testid="search-internal-id">
                <code className="font-mono text-xs text-muted-foreground">{result.internal_id}</code>
                <CopyIdentifier value={result.internal_id} />
              </span>
            ) : null}
          </div>
          {result.description ? <p className="mt-1 truncate text-sm text-muted-foreground">{result.description}</p> : null}
          {context ? <p className="mt-1 text-xs text-muted-foreground" data-testid="search-result-context">{context}</p> : null}
        </div>
        <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </div>
    </Card>
  );
  return result.url ? <Link to={result.url} className="block" aria-label={t("search.viewResult", { name: result.name ?? publicId })}>{content}</Link> : <div tabIndex={-1}>{content}</div>;
}
