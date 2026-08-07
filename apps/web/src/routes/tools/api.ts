/**
 * Tools API surface for the route files.
 *
 * SeqFetch / Enrichment / ExpPattern clients live in `@soymutdb/api-client`
 * (packages/api-client/src/tools.ts, added by Wave 3-A) — we re-export them
 * here so route imports stay in one place. `getAssemblies` (needed by the
 * SeqFetch region mode) is not part of the api-client tools module, so it is
 * implemented locally against GET /genes/assemblies.
 */
import { http } from "@soymutdb/api-client";

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
  ExpPatternResponse,
  ExpPatternRequest,
} from "@soymutdb/api-client";

// ---------------------------------------------------------------------------
// Assemblies (local — not part of the api-client tools module)
// ---------------------------------------------------------------------------

export interface AssemblyInfo {
  id: string;
  name: string;
  species: string;
  version: string;
  is_default: boolean;
}

export function getAssemblies(): Promise<AssemblyInfo[]> {
  return http.get<AssemblyInfo[]>("/genes/assemblies");
}
