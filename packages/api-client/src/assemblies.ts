/**
 * Genome assemblies of the current release, with counts aggregated per assembly.
 *
 * `statistics.download_count` is `null` on purpose and carries a
 * `download_count_reason`: `download_files` has no assembly dimension, so there
 * is no number to report. Do not substitute the release's download total, and
 * do not derive one from `category` — both would be invented data.
 */
import { http } from "./auth";

/** Counts aggregated from rows that carry the assembly id themselves. */
export interface AssemblyStatistics {
  gene_count: number;
  transcript_count: number;
  chromosome_count: number;
  total_length: number;
  /** Always `null`: no assembly dimension exists to aggregate over. */
  download_count: number | null;
  download_count_reason: string | null;
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
