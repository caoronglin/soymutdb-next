import { createFileRoute, Link, Outlet, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { ArrowRight, Beaker, Dna, FileText, Globe2, Search as SearchIcon } from "lucide-react";
import { Badge, Card, CardContent, EmptyState, Input, Skeleton } from "../lib/web-ui";
import { globalSearch, type FederatedSearchResponse, type SearchResponse, type SearchResult } from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";

const EXTERNAL_SOURCES = ["ncbi", "uniprot", "ensembl", "ebi"];

export const Route = createFileRoute("/search")({
  component: SearchComponent,
  validateSearch: ((search: Record<string, unknown>) => ({
    q: search.q ? String(search.q) : undefined,
    types: Array.isArray(search.types) ? search.types.map(String) : undefined,
    cursor: search.cursor ? String(search.cursor) : undefined,
    limit: search.limit ? Number(search.limit) : undefined,
    external: search.external === "1" || search.external === 1 || search.external === true,
    tissue: search.tissue ? String(search.tissue) : undefined,
    treatment: search.treatment ? String(search.treatment) : undefined,
    min_fpkm: search.min_fpkm ? Number(search.min_fpkm) : undefined,
  })) as any,
});

function isFederated(data: SearchResponse | FederatedSearchResponse): data is FederatedSearchResponse {
  return "sources" in data;
}

function isInternal(data: SearchResponse | FederatedSearchResponse): data is SearchResponse {
  return "results" in data;
}

const RESULT_ICONS: Record<string, typeof Dna> = {
  gene: Dna,
  variant: Dna,
  mutant_line: Beaker,
};

function SearchComponent() {
  const { q, types, cursor, limit, external } = Route.useSearch();
  const navigate = useNavigate();
  const [input, setInput] = React.useState(q ?? "");
  const [externalInput, setExternalInput] = React.useState(Boolean(external));

  React.useEffect(() => setInput(q ?? ""), [q]);
  React.useEffect(() => setExternalInput(Boolean(external)), [external]);

  const query = useQuery({
    queryKey: ["global-search", q, types, cursor, limit, external],
    queryFn: () => globalSearch({
      q: q!, types, cursor, limit: limit ?? 20,
      sources: external ? EXTERNAL_SOURCES : undefined,
    }),
    enabled: Boolean(q?.trim()),
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const next = input.trim();
    navigate({ to: "/search", search: {
      q: next || undefined, types: undefined, cursor: undefined,
      external: next ? externalInput : false, limit: next ? 20 : undefined,
      tissue: undefined, treatment: undefined, min_fpkm: undefined,
    } });
  };

  const data = query.data;
  const internal = data && isInternal(data) ? data : undefined;
  const federated = data && isFederated(data) ? data : undefined;
  const results = internal?.results ?? [];
  const hasOldData = Boolean(data) && query.isFetching;

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">Search</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">Discover SoyMutDB</h1>
        <p className="mt-3 max-w-2xl text-muted-foreground">Search genes, variants, mutant lines, publications, and connected external sources.</p>
      </FadeUp>

      <form onSubmit={submit} className="mt-10 space-y-3" role="search">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" role="searchbox" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Search genes, variants, publications…" aria-label="Search" className="h-12 pl-12" />
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input data-testid="external-source-toggle" type="checkbox" checked={externalInput} onChange={(event) => setExternalInput(event.target.checked)} />
          <Globe2 className="size-4" aria-hidden /> Search external sources (NCBI · UniProt · Ensembl · EBI)
        </label>
      </form>

      {!q ? <div className="mt-12"><EmptyState icon={SearchIcon} title="Start with a search" description="Enter a gene, variant, or publication to explore the database." /></div> : null}
      {q && query.isError ? <Card className="mt-10 border-destructive/40"><CardContent className="flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="font-medium">Search failed</p><p className="text-sm text-muted-foreground">Request ID: {(query.error as { request_id?: string })?.request_id ?? "unavailable"}</p></div><button type="button" className="rounded-md border px-3 py-2 text-sm" onClick={() => query.refetch()}>Retry</button></CardContent></Card> : null}
      {q && query.isLoading && !data ? <div data-testid="search-results" className="mt-10 grid gap-3">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-20 w-full" />)}</div> : null}

      {internal ? <section data-testid="search-results" className="mt-10" aria-label="Search results">
        <div className="mb-4 flex items-center justify-between text-sm text-muted-foreground"><span>Results for <span className="font-mono text-foreground">“{q}”</span>{hasOldData ? " · refreshing" : ""}</span>{internal.total_count !== null ? <span>{internal.total_count} results</span> : null}</div>
        {results.length === 0 ? <EmptyState icon={SearchIcon} title="No matches" description="No records matched this query. Try a broader term." /> : <div className="grid gap-3">{results.map((result) => <ResultRow key={`${result.type}-${result.id}`} result={result} />)}</div>}
      </section> : null}

      {federated ? <section data-testid="search-results" className="mt-10" aria-label="External search results"><div className="mb-4 text-sm text-muted-foreground">External results for <span className="font-mono text-foreground">“{q}”</span></div><div className="grid gap-6">{federated.sources.map((source) => <div key={source.source}><div className="mb-2 flex items-center gap-2"><h2 className="font-display font-semibold uppercase">{source.source}</h2><Badge variant="secondary">{source.status}</Badge><span className="text-xs text-muted-foreground">{source.health}</span></div>{source.error ? <p className="mb-2 text-sm text-muted-foreground">{source.error}</p> : null}{source.hits.length ? <div className="grid gap-2">{source.hits.map((hit, index) => <a key={`${hit.id ?? hit.title}-${index}`} href={hit.url ?? undefined} aria-disabled={!hit.url} tabIndex={hit.url ? undefined : -1} data-testid={hit.url ? "search-result-row" : "search-result-disabled"} data-url={hit.url ?? undefined} className={`flex items-center gap-3 rounded-lg border p-4 ${hit.url ? "transition-colors hover:border-primary" : "cursor-not-allowed opacity-60"}`}><div className="min-w-0 flex-1"><p className="font-medium">{hit.title}</p>{hit.snippet ? <p className="mt-1 truncate text-sm text-muted-foreground">{hit.snippet}</p> : null}</div><ArrowRight className="size-4 shrink-0" aria-hidden /></a>)}</div> : <p className="text-sm text-muted-foreground">No results from this source.</p>}</div>)}</div></section> : null}

      <div className="mt-14 pb-10"><Outlet /></div>
    </div>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  const Icon = RESULT_ICONS[result.type] ?? FileText;
  const content = <Card data-testid={result.url ? "search-result-row" : "search-result-disabled"} data-url={result.url ?? undefined} className={!result.url ? "opacity-60" : "card-lift"} aria-disabled={!result.url}><CardContent className="flex items-center gap-4"><div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground"><Icon className="size-5" aria-hidden /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><Badge variant="secondary" className="font-mono text-[10px] uppercase">{result.type}</Badge><p className="truncate font-medium">{result.name ?? result.id}</p></div>{result.description ? <p className="mt-1 truncate text-sm text-muted-foreground">{result.description}</p> : null}</div><ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden /></CardContent></Card>;
  return result.url ? <Link to={result.url} className="block" aria-label={`View ${result.name ?? result.id}`}>{content}</Link> : <div tabIndex={-1}>{content}</div>;
}
