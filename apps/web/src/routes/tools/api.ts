/**
 * Tools API surface for the route files.
 *
 * SeqFetch / Enrichment / ExpPattern clients live in `@soymutdb/api-client`
 * (packages/api-client/src/tools.ts) — they are re-exported here so route
 * imports stay in one place.
 */
export {
  seqFetchGenes,
  seqFetchRegion,
  runEnrichment,
  runExpPattern,
} from "@soymutdb/api-client";

export type {
  SeqFetchResponse,
  EnrichmentResponse,
  EnrichmentTerm,
  EnrichmentRequest,
  EnrichmentGseaResponse,
  EnrichmentGseaTerm,
  ExpPatternResponse,
  ExpPatternRequest,
} from "@soymutdb/api-client";
