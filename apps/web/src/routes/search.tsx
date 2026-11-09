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
import { Button, Card, Checkbox, Empty, Input, Select, Skeleton, Tag } from "@/lib/antd";
import {
  globalSearch,
  internalSearch,
  type AssemblyInfo,
  type InternalSearchResponse,
  type SearchResponse,
  type SearchResult,
  type SearchResultType,
} from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { queryKeys } from "../lib/query-keys";
import { SITE_VARIANT } from "../lib/site-variant";
import { useReleaseId } from "../lib/release-scope";
import { assembliesQueryOptions } from "../lib/query-options";
import { assemblyOptionLabel, resolveAssemblyParam, toAssemblyIdParam } from "../lib/assembly-selection";

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
    types: Array.isArray(search.types) ? search.types.map(String)
      : typeof search.types === "string" ? [search.types] : undefined,
    cursor: search.cursor ? String(search.cursor) : undefined,
    limit: Number.isInteger(Number(search.limit)) && Number(search.limit) >= 1
      && Number(search.limit) <= 50 ? Number(search.limit) : undefined,
    assembly: search.assembly ? String(search.assembly) : undefined,
  }),
});

function isCatalogSearch(data: SearchResponse | InternalSearchResponse): data is SearchResponse {
  return "results" in data;
}

/**
 * How the assembly context of the current request was resolved.
 *
 * - `unscoped` — no assembly requested; the API may answer across namespaces
 *   and the response has to carry the per-hit assembly identity.
 * - `pending` — the assembly catalogue has not arrived yet, so the parameter
 *   cannot be judged; the request waits instead of guessing.
 * - `blocked` — the parameter is unknown, ambiguous or unverifiable; no
 *   request is sent, because dropping the parameter would silently widen the
 *   result set into another genome namespace.
 * - `scoped` — resolved to exactly one assembly; its numeric id is sent.
 */
type AssemblyGate =
  | { kind: "unscoped" }
  | { kind: "pending" }
  | { kind: "blocked"; reason: "unknown" | "ambiguous" | "unavailable" }
  | { kind: "scoped"; id: number; assembly: AssemblyInfo };

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
    const known = SEARCH_RESULT_TYPES.filter((value) => types.includes(value));
    return known.length > 0 ? known : undefined;
  }, [types]);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isPortalSearchPage = pathname === "/search" || pathname === "/search/";
  const [input, setInput] = React.useState(q ?? "");

  React.useEffect(() => setInput(q ?? ""), [q]);

  const releaseId = useReleaseId();
  const internalSite = SITE_VARIANT === "internal";
  const resultLimit = limit ?? 20;
  const releaseNumber = releaseId && /^\d+$/.test(releaseId) ? Number(releaseId) : undefined;
  // The assembly catalogue is only needed to judge an assembly-scoped URL
  // parameter. The internal directory has no assembly dimension at all, so
  // the catalogue is not even requested there.
  const assembliesQuery = useQuery({
    ...assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
    enabled: !internalSite,
  });
  const assemblies = React.useMemo(() => assembliesQuery.data ?? [], [assembliesQuery.data]);
  const assemblyParam = assembly?.trim() ? assembly.trim() : undefined;
  const assemblyResolution = React.useMemo(
    () => resolveAssemblyParam(assemblies, assemblyParam),
    [assemblies, assemblyParam],
  );
  const assemblyGate = React.useMemo<AssemblyGate>(() => {
    if (internalSite || !assemblyParam) return { kind: "unscoped" };
    if (assembliesQuery.isError) return { kind: "blocked", reason: "unavailable" };
    if (assemblyResolution.status === "resolved") {
      const id = toAssemblyIdParam(assemblyResolution.assembly.id);
      return id === undefined
        ? { kind: "blocked", reason: "unavailable" }
        : { kind: "scoped", id, assembly: assemblyResolution.assembly };
    }
    // A name that matches several assemblies (v4/v5 share genome names) must
    // be reported, never collapsed onto the first match.
    if (assemblyResolution.status === "ambiguous") return { kind: "blocked", reason: "ambiguous" };
    if (assemblyResolution.status === "unknown") {
      // The catalogue has not arrived yet: wait for it instead of guessing.
      return assembliesQuery.isSuccess
        ? { kind: "blocked", reason: "unknown" }
        : { kind: "pending" };
    }
    return { kind: "unscoped" };
  }, [internalSite, assemblyParam, assemblyResolution, assembliesQuery.isError, assembliesQuery.isSuccess]);
  const assemblyOptions = React.useMemo(() => assemblies.map((candidate) => ({
    value: String(candidate.id),
    label: assemblyOptionLabel(candidate),
  })), [assemblies]);
  const assemblyLabels = React.useMemo(() => {
    const labels = new Map<string, string>();
    for (const candidate of assemblies) labels.set(String(candidate.id), assemblyOptionLabel(candidate));
    return labels;
  }, [assemblies]);
  const ambiguousMatches = assemblyResolution.status === "ambiguous"
    ? assemblyResolution.matches.map(assemblyOptionLabel)
    : [];
  const requestAssemblyId = assemblyGate.kind === "scoped" ? assemblyGate.id : undefined;
  // A missing assembly context must never reach the API: dropping the
  // parameter would silently widen the result set into another namespace.
  const assemblyContextMissing = assemblyGate.kind === "blocked" || assemblyGate.kind === "pending";
  const scope = JSON.stringify([q, selectedTypes, assembly, releaseId, resultLimit, SITE_VARIANT]);
  const [cursorPath, setCursorPath] = React.useState<{
    scope: string; cursors: (string | undefined)[]; resetCursor?: string;
  }>(() => ({ scope, cursors: [cursor] }));
  // Never issue a new-scope request with the previous scope's cursor, even
  // during the render before the URL reset effect runs. Initial deep links stay valid.
  const scopedCursor = !internalSite && cursorPath.scope === scope
    && (!cursor || cursor !== cursorPath.resetCursor) ? cursor : undefined;
  const cursorIndex = cursorPath.scope === scope ? cursorPath.cursors.lastIndexOf(scopedCursor) : -1;
  React.useEffect(() => {
    if (!isPortalSearchPage || cursorPath.scope === scope) return;
    setCursorPath({ scope, cursors: [undefined], resetCursor: cursor });
    if (cursor) void navigate({ to: "/search", replace: true, search: {
      q, types, assembly, limit, cursor: undefined,
    } });
  }, [scope, cursorPath.scope, cursor, navigate, q, types, assembly, limit, isPortalSearchPage]);
  // Federated (external-source) search is retired permanently: the portal only
  // ever queries its own catalogue or the internal directory.
  const query = useQuery<SearchResponse | InternalSearchResponse>({
    queryKey: queryKeys.search.global({
      query: q,
      // The narrowed selection keys the cache, so an all-unknown `?types=`
      // URL cannot reuse the unfiltered entry.
      types: selectedTypes,
      cursor: scopedCursor,
      limit: resultLimit,
      // The canonical assembly id scopes the cache exactly like the request.
      assemblyId: requestAssemblyId != null ? String(requestAssemblyId) : undefined,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () => {
      if (!internalSite && assemblyContextMissing) {
        return Promise.reject(new Error("Assembly context is unresolved"));
      }
      return internalSite
        ? internalSearch(q!, { limit: resultLimit })
        : globalSearch({
            q: q!,
            types: selectedTypes,
            cursor: scopedCursor,
            limit: resultLimit,
            assembly_id: requestAssemblyId,
            release_id: releaseNumber,
          });
    },
    enabled: isPortalSearchPage && Boolean(q?.trim()) && !assemblyContextMissing,
    staleTime: 60_000,
  });

  const runSearch = (raw: string) => {
    const next = raw.trim();
    void navigate({ to: "/search", search: {
      q: next || undefined, types: selectedTypes, cursor: undefined,
      assembly, limit,
    } });
  };

  // `/search` is the portal search page; every route beneath it (`/search/genes`,
  // `/search/location`, `/search/blast`, …) is a standalone tool page with its own
  // heading, form and result table. Rendering the portal hero and the global search
  // box for those children contradicts the approved reference structure and pushes
  // each tool's own form below a full screen of unrelated content.
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
  // Distribution counts can describe gene matches or only the current page,
  // depending on the query. Use their assembly keys for disambiguation without
  // presenting those counts as result totals. Offer only resolvable scopes.
  const assemblyBreakdown = Object.entries(catalog?.by_assembly ?? {})
    .map(([id, count]) => {
      const candidate = assemblies.find((entry) => String(entry.id) === id);
      return candidate ? { id, count, label: assemblyOptionLabel(candidate) } : null;
    })
    .filter((entry): entry is { id: string; count: number; label: string } => entry !== null)
    .sort((left, right) => right.count - left.count);
  const crossAssembly = catalog !== undefined
    && (catalog.ambiguous === true || Object.keys(catalog.by_assembly ?? {}).length > 1);
  const updateTypes = (values: SearchResultType[]) => {
    void navigate({ to: "/search", search: { q, assembly, limit, types: values.length ? values : undefined, cursor: undefined } });
  };
  /**
   * Scope the query to one assembly. The canonical numeric id travels in the
   * URL (deep links, cache keys and the request all use it) and the cursor is
   * cleared, because a cursor belongs to the previous result set.
   */
  const selectAssembly = (value: string | undefined) => {
    void navigate({ to: "/search", search: {
      q, types: selectedTypes, limit,
      assembly: value,
      cursor: undefined,
    } });
  };
  const nextPage = () => {
    if (!catalog?.has_more || !catalog.next_cursor || query.isFetching) return;
    const next = catalog.next_cursor;
    const prefix = cursorIndex >= 0 ? cursorPath.cursors.slice(0, cursorIndex + 1) : [scopedCursor];
    setCursorPath({ ...cursorPath, scope, cursors: [...prefix, next] });
    void navigate({ to: "/search", search: { q, types, assembly, limit, cursor: next } });
  };
  const previousPage = () => {
    const previous = cursorIndex > 0 ? cursorPath.cursors[cursorIndex - 1] : undefined;
    if (cursorIndex > 0) setCursorPath({ ...cursorPath, scope, cursors: cursorPath.cursors.slice(0, cursorIndex) });
    void navigate({ to: "/search", search: { q, types, assembly, limit, cursor: previous } });
  };

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

      {!internalSite ? <fieldset className="mt-4 flex flex-wrap items-center gap-3">
        <legend className="mb-2 text-sm font-medium">{t("search.typeFilter.label")}</legend>
        <Button size="small" onClick={() => updateTypes([])} aria-pressed={!selectedTypes?.length}>
          {t("search.typeFilter.all")}
        </Button>
        <Checkbox.Group
          value={selectedTypes ?? []}
          options={SEARCH_RESULT_TYPES.map((value) => ({ value, label: t(`search.typeFilter.${value === "mutant_line" ? "mutantLine" : value}`) }))}
          onChange={(values) => updateTypes(values as SearchResultType[])}
        />
      </fieldset> : null}

      {/* The genome version is an explicit part of a search: v4 and v5 are
          distinct namespaces, so the request carries the canonical assembly id
          and the picker writes that id back into the URL. */}
      {!internalSite ? <div className="mt-4 flex flex-wrap items-center gap-3" data-testid="search-assembly-scope">
        <label htmlFor="search-assembly" className="text-sm font-medium">{t("search.assemblyLabel")}</label>
        <Select
          id="search-assembly"
          className="min-w-[240px]"
          allowClear
          value={assemblyGate.kind === "scoped" ? String(assemblyGate.assembly.id) : undefined}
          placeholder={t("search.assemblyPlaceholder")}
          loading={assembliesQuery.isLoading}
          options={assemblyOptions}
          onChange={(value) => selectAssembly(typeof value === "string" ? value : undefined)}
          data-testid="search-assembly-select"
        />
      </div> : null}

      {assemblyGate.kind === "blocked" ? <Card className="mt-6 border-destructive/40" data-testid="search-assembly-blocked">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5">
          <div>
            <p className="font-medium">
              {assemblyGate.reason === "ambiguous"
                ? t("search.ambiguousAssembly", { matches: ambiguousMatches.join(", ") })
                : assemblyGate.reason === "unavailable"
                  ? t("home.assembliesUnavailable")
                  : t("search.assemblyUnavailable")}
            </p>
            {assemblyGate.reason === "unavailable"
              ? <p className="mt-1 text-sm text-muted-foreground">{t("search.assemblyUnavailable")}</p>
              : null}
          </div>
          {assemblyGate.reason === "unavailable"
            ? <Button onClick={() => void assembliesQuery.refetch()}>{t("common.retry")}</Button>
            : <Button onClick={() => selectAssembly(undefined)}>{t("common.reset")}</Button>}
        </div>
      </Card> : null}

      {!q ? <div className="mt-12"><Empty image={<SearchIcon style={{ fontSize: 40, color: "var(--muted-foreground)" }} />} description={<><p className="font-medium">{t("search.emptyPromptTitle")}</p><p className="text-sm text-muted-foreground">{t("search.emptyPromptDescription")}</p></>} /></div> : null}
      {q && query.isError ? <Card className="mt-10 border-destructive/40"><div className="flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="font-medium">{t("search.errorTitle")}</p><p className="text-sm text-muted-foreground">{t("common.requestId")}: {(query.error as { request_id?: string })?.request_id ?? t("common.notAvailable")}</p></div><Button onClick={() => void query.refetch()}>{t("common.retry")}</Button></div></Card> : null}
      {q && (query.isLoading || assemblyGate.kind === "pending") && !data ? <div data-testid="search-results" className="mt-10 grid gap-3">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-20 w-full" />)}</div> : null}

      {crossAssembly && !assemblyContextMissing ? <div className="mt-6 rounded-xl border border-border/70 bg-card p-4" data-testid="search-ambiguous-notice">
        <p className="font-medium">{t("search.ambiguousNotice")}</p>
        {assemblyBreakdown.length > 0 ? <ul className="mt-3 flex flex-wrap gap-2">
          {assemblyBreakdown.map((entry) => <li key={entry.id}>
            <Button
              size="small"
              data-testid={`search-assembly-option-${entry.id}`}
              onClick={() => selectAssembly(entry.id)}
            >
              <span className="font-mono">{entry.label}</span>
            </Button>
          </li>)}
        </ul> : null}
      </div> : null}

      {(catalog || directory) && !assemblyContextMissing ? <section data-testid="search-results" className="mt-10" aria-label={t("search.resultsAria")}>
        <div className="mb-4 flex items-center justify-between text-sm text-muted-foreground"><span>{t("search.resultsFor")} <span className="font-mono text-foreground">“{q}”</span>{isRefreshing ? <span> · {t("search.refreshing")}</span> : null}</span>{totalCount !== null ? <span>{t("search.resultCount", { count: totalCount })}</span> : null}</div>
        {results.length === 0 ? <Empty image={<SearchIcon style={{ fontSize: 40, color: "var(--muted-foreground)" }} />} description={<><p className="font-medium">{t("search.noResults")}</p><p className="text-sm text-muted-foreground">{t("search.noMatchesDescription")}</p></>} /> : <div className="grid gap-3">{results.map((result) => <ResultRow key={`${result.type}-${result.id}-${result.internal_id ?? "public"}`} result={result} assemblyLabels={assemblyLabels} />)}</div>}
        {catalog && !internalSite ? <nav className="mt-6 flex justify-center gap-3" aria-label={t("common.pagination")}>
          <Button onClick={previousPage} disabled={!scopedCursor || query.isFetching}>
            {t(cursorIndex > 0 ? "common.previous" : "genes.first")}
          </Button>
          <Button onClick={nextPage} disabled={!catalog.has_more || !catalog.next_cursor || query.isFetching || query.isError}>
            {t("common.next")}
          </Button>
        </nav> : null}
        {directory ? <p className="mt-4 text-sm text-muted-foreground">{t("search.internalNotPaginated")}</p> : null}
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

function ResultRow({ result, assemblyLabels }: {
  result: SearchResult;
  /** Canonical assembly id → display label, for hits that carry only an id. */
  assemblyLabels?: Map<string, string>;
}) {
  const { t } = useTranslation();
  const Icon = RESULT_ICONS[result.type] ?? FileText;
  const publicId = result.public_id ?? result.id;
  // Every hit states the genome namespace it belongs to: an unscoped match
  // may span v4 and v5, and a silently collapsed list would hide that.
  const assemblyLabel = result.assembly
    ?? (result.assembly_id != null ? assemblyLabels?.get(String(result.assembly_id)) : undefined);
  const context = [
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
            {assemblyLabel ? <Tag data-testid="search-result-assembly" className="font-mono text-[10px] uppercase">{assemblyLabel}</Tag> : null}
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
