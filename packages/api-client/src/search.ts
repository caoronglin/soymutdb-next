import { http } from "./auth";

export type SearchResultType = "gene" | "variant" | "mutant_line" | "phenotype" | "publication";

export interface SearchResult {
  type: SearchResultType;
  id: string;
  name?: string;
  description?: string;
  url?: string;
  source?: string;
  score?: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  by_type: Record<string, number>;
  cursor: string | null;
  next_cursor: string | null;
  has_more: boolean;
  total_count: number | null;
}

/** A single external hit returned by a federated search source. */
export interface FederatedHit {
  source: string;
  title: string;
  url: string;
  snippet?: string;
  id?: string;
  extra?: Record<string, unknown>;
}

/**
 * One federated search source with its per-source degradation state. Mirrors
 * the backend `_external_json_payload` shape returned by `/search` when
 * `sources` is supplied (external federated search).
 */
export interface FederatedSource {
  source: string;
  status: string;
  hits: FederatedHit[];
  elapsed?: number;
  elapsed_ms?: number;
  error?: string | null;
  health?: string;
}

/**
 * Federated external search response (`/search?sources=...`). The `/search`
 * endpoint returns this shape when external `sources` are requested (content
 * negotiation produces the internal `SearchResponse` otherwise).
 */
export interface FederatedSearchResponse {
  query: string;
  sources: FederatedSource[];
  total_hits: number;
  elapsed_ms?: number;
}

export interface SearchSuggestion { text: string; type: string; id?: string; }

export interface SearchParams {
  q: string;
  types?: SearchResultType[];
  sources?: string[];
  cursor?: string;
  limit?: number;
}

export function globalSearch(
  params: SearchParams,
): Promise<SearchResponse | FederatedSearchResponse> {
  return http.get<SearchResponse | FederatedSearchResponse>("/search", { params });
}

export function getSearchSuggestions(q: string, limit = 10): Promise<SearchSuggestion[]> {
  return http.get<SearchSuggestion[]>("/search/suggest", { params: { q, limit } });
}
