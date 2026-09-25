/**
 * Typed public tools endpoints (seqfetch / enrichment / exppattern).
 *
 * All three are public utilities — no authentication. Calls use the pure
 * `request` transport with `auth: false` so no Bearer header is attached.
 *
 * Types come from the generated OpenAPI schema
 * (`./generated/openapi.d.ts`); the exppattern endpoint has no backend
 * response_model (raw dict), so its response shape is documented locally.
 */

import type { components } from "./generated/openapi";
import { request, TimeoutPresets } from "./client";

export type SeqFetchRequest = components["schemas"]["SeqFetchRequest"];
export type SeqFetchResponse = components["schemas"]["SeqFetchResponse"];
export type EnrichmentRequest = Omit<
  components["schemas"]["EnrichmentRequest"],
  "genes"
> & {
  /** Required assembly database id used for input and background annotations. */
  assembly_id: number;
  genes: string[];
};
type AssemblyScopedAnalysis = {
  assembly_id: number;
  release_id: number;
  assembly_name: string;
  assembly_version: string;
};
export type EnrichmentSource = {
  name: string;
  version: string;
  url: string;
  sha256: string;
  imported_at: string;
};
type EnrichmentSourceContext = {
  annotation_source: EnrichmentSource | null;
};
export type EnrichmentResponse =
  components["schemas"]["EnrichmentResponse"] &
  AssemblyScopedAnalysis &
  EnrichmentSourceContext;
export type EnrichmentTerm = components["schemas"]["EnrichmentTerm"];
export type EnrichmentGseaResponse =
  components["schemas"]["EnrichmentGseaResponse"] &
  AssemblyScopedAnalysis &
  EnrichmentSourceContext;
export type EnrichmentGseaTerm = components["schemas"]["EnrichmentGseaTerm"];
export type ExpPatternRequest = Omit<
  components["schemas"]["ExpPatternRequest"],
  "genes"
> & {
  /** Required assembly database id; included here until the OpenAPI snapshot is regenerated. */
  assembly_id: number;
  genes: string[];
};

/**
 * Exppattern response shape (local — the backend route returns a raw dict
 * without a response_model, so no generated schema exists; see
 * apps/api/app/api/v1/tools_exppattern.py). `matrix` is row-major with
 * `null` for missing expression; `value_range` is `[min, max]` over
 * non-null cells (`[null, null]` when empty).
 */
export interface ExpPatternResponse {
  assembly_id: number;
  release_id: number;
  assembly_name: string;
  assembly_version: string;
  genes: string[];
  conditions: string[];
  matrix: (number | null)[][];
  row_order: number[];
  clustering: "input" | "mean_sort" | "hierarchical" | "none";
  value_range: [number | null, number | null];
  missing_genes: string[];
  scale: "zscore" | "none";
}

/** Batch-extract FASTA for up to 200 gene IDs in one explicit assembly. */
export function seqFetchGenes(assembly: string, genes: string[]): Promise<SeqFetchResponse> {
  return request<SeqFetchResponse>("/tools/seqfetch", {
    method: "POST",
    auth: false,
    json: { assembly, genes } satisfies SeqFetchRequest,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

/** Extract a single 1-based `chr:start-end` interval from a named assembly. */
export function seqFetchRegion(
  assembly: string,
  region: string,
): Promise<SeqFetchResponse> {
  return request<SeqFetchResponse>("/tools/seqfetch", {
    method: "POST",
    auth: false,
    json: { assembly, region } satisfies SeqFetchRequest,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

/** GO/KEGG hypergeometric enrichment over a gene list (public). */
export function runEnrichment(
  req: EnrichmentRequest,
): Promise<EnrichmentResponse | EnrichmentGseaResponse> {
  return request<EnrichmentResponse | EnrichmentGseaResponse>("/tools/enrichment", {
    method: "POST",
    auth: false,
    json: req,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

/** Build a gene × condition expression matrix, optionally scaled/clustered. */
export function runExpPattern(req: ExpPatternRequest): Promise<ExpPatternResponse> {
  return request<ExpPatternResponse>("/tools/exppattern", {
    method: "POST",
    auth: false,
    json: req,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}
