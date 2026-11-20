/**
 * Genome assemblies of the current release, with counts aggregated per assembly.
 *
 * Every statistic is an `AssemblyMetric`, not a bare number. A count that could
 * not be derived from the authoritative tables arrives as `value: null` plus a
 * machine-readable `reason`; a count that ran and found nothing arrives as a
 * genuine `0` with no reason. A caller that collapses the two loses the whole
 * distinction, so render `null` as "not counted (because …)", never as `0`.
 *
 * `statistics.download_count` is always the first kind: `download_files` has no
 * assembly dimension. Do not substitute the release's download total, and do not
 * derive one from `category` — both would be invented data.
 */
import { http } from "./auth";

/** One statistic: a count, or an explained absence. Never both. */
export interface AssemblyMetric {
  /** `null` when the count could not be derived. */
  value: number | null;
  /** Reason code for a `null` value; always `null` when `value` is present. */
  reason: string | null;
}

/** Counts aggregated from rows that carry the assembly id themselves. */
export interface AssemblyStatistics {
  gene_count: AssemblyMetric;
  transcript_count: AssemblyMetric;
  chromosome_count: AssemblyMetric;
  total_length: AssemblyMetric;
  /** Always unknown: no assembly dimension exists to aggregate over. */
  download_count: AssemblyMetric;
}

export interface AssemblySummary {
  id: string | number;
  name: string;
  species: string;
  version: string;
  description: string | null;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
  release_id: number | null;
  release_version: string | null;
  statistics: AssemblyStatistics;
}

export interface AssemblyChromosome {
  id: string | number;
  assembly_id: string | number;
  name: string;
  length: number;
  order: number;
}

export interface AssemblyDetail extends AssemblySummary {
  chromosomes: AssemblyChromosome[];
}

/** List the resolved release's assemblies (GET /assemblies). */
export function listAssemblies(): Promise<AssemblySummary[]> {
  return http.get<AssemblySummary[]>("/assemblies");
}

/** One assembly of the resolved release (GET /assemblies/{id}). */
export function getAssembly(assemblyId: string | number): Promise<AssemblyDetail> {
  return http.get<AssemblyDetail>(`/assemblies/${assemblyId}`);
}
