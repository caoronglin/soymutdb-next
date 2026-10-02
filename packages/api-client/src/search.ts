import type { components } from "./generated/openapi";
import { http } from "./auth";

export type SearchResultType = "gene" | "variant" | "mutant_line" | "phenotype" | "publication";

/**
 * How a search row matched the query. Mirrors the backend `MatchType` enum via
 * the generated contract; stays optional on the row because an older backend
 * payload omits it.
 */
export type MatchType = components["schemas"]["MatchType"];

/**
 * One explicit, provenance-bearing cross-version relation attached to a gene
 * hit (OPT-01 / frozen contract). The relation is assembly-scoped and is only
 * ever populated from an explicit crosswalk, never inferred from name or
 * coordinate similarity. Optional end-to-end: a backend without the crosswalk
 * field yields an empty/absent list and the UI must not require it.
 */
export interface CrossVersionLink {
  gene_accession: string;
  assembly_id?: number | null;
  assembly_name?: string | null;
  assembly_version?: string | null;
  relation_type: string;
  provenance_source: string;
  match_type?: MatchType;
}

export interface SearchResult {
  type: SearchResultType;
  id: string;
  /**
   * Canonical public identity when the response carries the audience-explicit
   * dual identity (internal-site search). Falls back to `id` for public
   * results, where `id` is already the public identity. Never the private
   * persistence key.
   */
  public_id?: string;
  /**
   * Private internal identifier. Served only to the authenticated internal
   * site; the external site variant must never render it, place it in an
   * attribute, or log it.
   */
  internal_id?: string;
  name?: string;
  description?: string;
  url?: string;
  source?: string;
  score?: number;
  release_id?: number | null;
  assembly_id?: number | null;
  /** Human-readable genome version label (name + version); display only. */
  assembly?: string | null;
  /** How this row matched (exact | alias | cross-version | text); optional. */
  match_type?: MatchType;
  /** Provenance-bearing cross-version relations for a gene hit; optional. */
  cross_version?: CrossVersionLink[];
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  by_type: Record<string, number>;
  /** Match counts per assembly over the full release-scoped result set. */
  by_assembly?: Record<string, number>;
  /** True when an unscoped query matched more than one assembly. */
  ambiguous?: boolean;
  cursor: string | null;
  next_cursor: string | null;
  has_more: boolean;
  total_count: number | null;
}

export interface SearchSuggestion { text: string; type: string; id?: string; }

export interface SearchParams {
  q: string;
  types?: SearchResultType[];
  cursor?: string;
  limit?: number;
  assembly_id?: number;
  /** Explicit release scope for pinned public searches. */
  release_id?: number;
}

// External federated search (NCBI/UniProt/Ensembl/EBI) is retired permanently:
// the `sources` request parameter and the `{sources, total_hits}` response shape
// are gone, so this always resolves to the catalogue response.
export function globalSearch(params: SearchParams): Promise<SearchResponse> {
  const { q, ...rest } = params;
  return http.get<SearchResponse>("/search", {
    params: { ...rest, query: q },
  });
}

export function getSearchSuggestions(q: string, limit = 10): Promise<SearchSuggestion[]> {
  return http.get<SearchSuggestion[]>("/search/suggest", { params: { q, limit } });
}

// ---------------------------------------------------------------- internal
// Authorized internal-site search. The route is server-side authorized (not
// merely hidden by the UI) and returns BOTH identities so an operator can
// disambiguate and copy the private key. Types come straight from the generated
// OpenAPI contract.

export type InternalMutantSearchItem = components["schemas"]["InternalMutantSearchItem"];
export type InternalGeneSearchItem = components["schemas"]["InternalGeneSearchItem"];
export type InternalSearchResponse = components["schemas"]["InternalSearchResponse"];

export interface InternalSearchParams {
  /** Server clamps to 1..100; defaults to 20 server-side. */
  limit?: number;
}

/**
 * GET /api/v1/search/internal — authenticated, unaudited-cache-bypassing
 * internal search. Uses the coordinated `http` wrapper so the Authorization
 * header and the release pin are attached by the shared transport.
 */
export function internalSearch(
  query: string,
  opts: InternalSearchParams = {},
): Promise<InternalSearchResponse> {
  return http.get<InternalSearchResponse>("/search/internal", {
    params: { query, limit: opts.limit },
  });
}
