/** Read-only OLS4 ontology query client. */

import { http } from "./client";

export interface OntologySearchResult {
  term_id: string | null;
  label: string | null;
  iri: string;
  ontology_name: string | null;
  description: string[];
  synonyms: string[];
  is_obsolete: boolean;
}

export interface OntologySearchResponse {
  query: string;
  ontology: string | null;
  count: number;
  items: OntologySearchResult[];
}

export interface OntologyTermResponse {
  iri: string;
  label: string | null;
  ontology_name: string | null;
  description: string[];
  synonyms: string[];
  is_obsolete: boolean;
  parents: string[];
  children: string[];
}

export interface OntologyRelationshipGraphNode {
  iri: string;
  label: string | null;
  is_obsolete: boolean;
}

export interface OntologyRelationshipGraphEdge {
  source: string;
  target: string;
  label: string | null;
}

export interface OntologyRelationshipGraphResponse {
  ontology: string;
  root_iri: string;
  nodes: OntologyRelationshipGraphNode[];
  edges: OntologyRelationshipGraphEdge[];
  truncated: boolean;
}

export const ontologyApi = {
  search(params: {
    query: string;
    ontology?: string;
    limit?: number;
  }) {
    return http.get<OntologySearchResponse>("/ontology/search", { params });
  },
  term(params: { ontology: string; iri: string }) {
    return http.get<OntologyTermResponse>("/ontology/term", { params });
  },
  relationshipGraph(params: {
    ontology: string;
    iri: string;
    max_nodes?: number;
    max_edges?: number;
  }) {
    return http.get<OntologyRelationshipGraphResponse>("/ontology/graph", { params });
  },
};
