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
export type EnrichmentRequest = components["schemas"]["EnrichmentRequest"];
export type EnrichmentResponse = components["schemas"]["EnrichmentResponse"];
export type EnrichmentTerm = components["schemas"]["EnrichmentTerm"];
export type ExpPatternRequest = components["schemas"]["ExpPatternRequest"];

/**
 * Exppattern response shape (local — the backend route returns a raw dict
 * without a response_model, so no generated schema exists; see
 * apps/api/app/api/v1/tools_exppattern.py). `matrix` is row-major with
 * `null` for missing expression; `value_range` is `[min, max]` over
 * non-null cells (`[null, null]` when empty).
 */
export interface ExpPatternResponse {
  genes: string[];
  conditions: string[];
  matrix: (number | null)[][];
  row_order: number[];
  clustering: "input" | "mean_sort" | "hierarchical" | "none";
  value_range: (number | null)[];
  missing_genes: string[];
  scale: "zscore" | "none";
}

/** Batch-extract FASTA for up to 200 gene IDs (unknown IDs land in `missing`). */
export function seqFetchGenes(genes: string[]): Promise<SeqFetchResponse> {
  return request<SeqFetchResponse>("/tools/seqfetch", {
    method: "POST",
    auth: false,
    json: { genes } satisfies SeqFetchRequest,
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
export function runEnrichment(req: EnrichmentRequest): Promise<EnrichmentResponse> {
  return request<EnrichmentResponse>("/tools/enrichment", {
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
