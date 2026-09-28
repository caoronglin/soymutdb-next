import type { components } from "./generated/openapi";
import { http } from "./auth";

/**
 * Typed stats endpoints.
 *
 * Response/request types for implemented endpoints come from the generated
 * OpenAPI schema (`./generated/openapi.d.ts`) — regenerate via
 * `pnpm --filter @soymutdb/api-client generate:api-client` after backend
 * contract changes.  DTOs for endpoints that are not yet implemented
 * backend-side are kept local (unused by the current frontend).
 */

// --- Generated types (backend contract) ------------------------------------

export type HomepageStats = components["schemas"]["HomepageStats"];
export type ChromosomeDensity = components["schemas"]["ChromosomeDensitySummary"];
export type ImpactSummaryItem = components["schemas"]["ImpactSummaryItem"];
export type VariantTypeSummaryItem = components["schemas"]["VariantTypeSummaryItem"];
export type DiscoveryTrendItem = components["schemas"]["DiscoveryTrendPoint"];
export type ReleaseStats = components["schemas"]["ReleaseSummary"];
export type MutagenCount = components["schemas"]["MutagenCount"];
export type ErrorResponse = components["schemas"]["ErrorResponse"];
export type ValidationErrorResponse = components["schemas"]["ValidationErrorResponse"];

// --- Local DTOs for not-yet-implemented endpoints (kept until backend lands) --

export interface SubstitutionSpectrumItem {
  substitution: string;
  count: number;
  proportion: number;
}

export interface QualityDistributionItem {
  quality_bin: string;
  count: number;
}

export interface EffectDistributionItem {
  effect: string;
  count: number;
  impact: string;
}

export interface MutantLineVariantCount {
  line_id: string;
  line_name: string;
  variant_count: number;
  snp_count: number;
  indel_count: number;
}

export interface FunctionalSummary {
  coding_variants: number;
  non_coding_variants: number;
  exonic_variants: number;
  intronic_variants: number;
  utr_variants: number;
  upstream_variants: number;
  downstream_variants: number;
  intergenic_variants: number;
}

// --- Endpoint functions -----------------------------------------------------

export function fetchHomepageStats(): Promise<HomepageStats> {
  return http.get<HomepageStats>("/stats/homepage");
}

// `fetchReleaseStatistics` was removed: it targeted `/stats/releases`, which the
// API does not serve. Per-release counts come from `listReleases()` rows.

/**
 * Variant-type summary for the release this client is pinned to.
 *
 * There is no per-call release parameter: the server scope comes from the
 * `X-SoyMutDB-Release` header that `setReleaseId()` installs, so a caller
 * cannot widen the read by passing a different id.
 */
export function fetchVariantTypeSummary(): Promise<VariantTypeSummaryItem[]> {
  return http.get<VariantTypeSummaryItem[]>("/stats/summary/variant-types");
}

/** Impact summary for the client's pinned release. */
export function fetchImpactSummary(): Promise<ImpactSummaryItem[]> {
  return http.get<ImpactSummaryItem[]>("/stats/summary/impact");
}

/** Mutant lines per mutagen for the client's pinned release. */
export function fetchMutagenStatistics(): Promise<MutagenCount[]> {
  return http.get<MutagenCount[]>("/stats/mutagens");
}

/** Per-chromosome variant density for the client's pinned release. */
export function fetchChromosomeDensity(): Promise<ChromosomeDensity[]> {
  return http.get<ChromosomeDensity[]>("/stats/chromosome-density");
}

/** Cumulative discovery trend across published releases. */
export function fetchDiscoveryTrend(days = 30): Promise<DiscoveryTrendItem[]> {
  return http.get<DiscoveryTrendItem[]>("/stats/discovery-trend", {
    params: { days },
  });
}


// Removed: `fetchSubstitutionSpectrum`, `fetchQualityDistribution`,
// `fetchEffectDistribution`, `fetchMutantLineVariantCounts` and
// `fetchFunctionalSummary` targeted `/stats/{substitution-spectrum,
// quality-distribution,effect-distribution,mutant-line-variants,
// functional-summary}`. None of those routes exist in the API (see
// apps/api/app/api/v1/stats.py), so every call was a guaranteed 404 dressed up
// as a typed client method. Add the endpoint and the client together.

