import { http } from "./auth";

export type SearchResultType = "gene" | "variant" | "mutant_line" | "phenotype" | "publication";

export interface SearchResult {
  type: SearchResultType;
  id: string;
  name?: string;
  description?: string;
  url?: string;
  source?: string;
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

export interface SearchSuggestion { text: string; type: string; id?: string; }

export interface SearchParams {
  q: string;
  types?: SearchResultType[];
  sources?: string[];
  cursor?: string;
  limit?: number;
}

export function globalSearch(params: SearchParams): Promise<SearchResponse> {
  return http.get<SearchResponse>("/search", { params });
}

export function getSearchSuggestions(q: string, limit = 10): Promise<SearchSuggestion[]> {
  return http.get<SearchSuggestion[]>("/search/suggest", { params: { q, limit } });
}
