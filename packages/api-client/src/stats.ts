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

export function fetchVariantTypeSummary(
  releaseId?: string,
): Promise<VariantTypeSummaryItem[]> {
  return http.get<VariantTypeSummaryItem[]>("/stats/summary/variant-types", {
    params: { release_id: releaseId },
  });
}

export function fetchImpactSummary(
  releaseId?: string,
): Promise<ImpactSummaryItem[]> {
  return http.get<ImpactSummaryItem[]>("/stats/summary/impact", {
    params: { release_id: releaseId },
  });
}

export function fetchMutagenStatistics(
  releaseId?: string,
): Promise<MutagenCount[]> {
  return http.get<MutagenCount[]>("/stats/mutagens", {
    params: { release_id: releaseId },
  });
}

export function fetchChromosomeDensity(
  releaseId?: string,
): Promise<ChromosomeDensity[]> {
  return http.get<ChromosomeDensity[]>("/stats/chromosome-density", {
    params: { release_id: releaseId },
  });
}

export function fetchSubstitutionSpectrum(
  releaseId?: string,
): Promise<SubstitutionSpectrumItem[]> {
  return http.get<SubstitutionSpectrumItem[]>("/stats/substitution-spectrum", {
    params: { release_id: releaseId },
  });
}

export function fetchQualityDistribution(
  releaseId?: string,
): Promise<QualityDistributionItem[]> {
  return http.get<QualityDistributionItem[]>("/stats/quality-distribution", {
    params: { release_id: releaseId },
  });
}

export function fetchEffectDistribution(
  releaseId?: string,
): Promise<EffectDistributionItem[]> {
  return http.get<EffectDistributionItem[]>("/stats/effect-distribution", {
    params: { release_id: releaseId },
  });
}

export function fetchMutantLineVariantCounts(
  limit = 20,
  releaseId?: string,
): Promise<MutantLineVariantCount[]> {
  return http.get<MutantLineVariantCount[]>("/stats/mutant-line-variants", {
    params: { limit, release_id: releaseId },
  });
}

export function fetchDiscoveryTrend(
  days = 30,
  releaseId?: string,
): Promise<DiscoveryTrendItem[]> {
  return http.get<DiscoveryTrendItem[]>("/stats/discovery-trend", {
    params: { days, release_id: releaseId },
  });
}

export function fetchFunctionalSummary(
  releaseId?: string,
): Promise<FunctionalSummary> {
  return http.get<FunctionalSummary>("/stats/functional-summary", {
    params: { release_id: releaseId },
  });
}
