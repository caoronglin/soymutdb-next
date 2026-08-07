import { http } from "./client";

export interface SearchResult {
  type: "gene" | "variant" | "mutant_line" | "documentation" | "expression";
  id: string;
  name: string;
  description?: string;
  url?: string;
}

export interface SearchResponse {
  query: string;
  total: number;
  results: SearchResult[];
  by_type: {
    gene: number;
    variant: number;
    mutant_line: number;
    documentation: number;
    expression?: number;
  };
}

export interface SearchSuggestion {
  text: string;
  type: string;
  id?: string;
}

export interface SearchParams {
  q: string;
  type?: string;
  page?: number;
  page_size?: number;
}

export function globalSearch(params: SearchParams): Promise<SearchResponse> {
  return http.get<SearchResponse>("/search", { params });
}

export function getSearchSuggestions(q: string, limit = 10): Promise<SearchSuggestion[]> {
  return http.get<SearchSuggestion[]>("/search/suggest", { params: { q, limit } });
}
