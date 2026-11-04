/**
 * Phenotype scanning for `/phenotypes`.
 *
 * ## Why a scan and not a list endpoint
 *
 * The backend exposes phenotype observations *per mutant line*
 * (`GET /mutants/{public_id}/phenotypes`) and nothing across lines. There is no
 * endpoint that returns "all phenotypes matching trait category X", so this
 * page cannot simply page a server-side filter.
 *
 * Rather than invent a list that does not exist, the page scans the public
 * mutant-line set with a bounded budget: each line is read through the same
 * per-line endpoint the detail page uses, and the caller is told exactly how
 * much of the set was read. A truncated scan is reported as truncated — it is
 * never presented as the complete answer.
 *
 * The scan is cache-first (`queryClient.ensureQueryData`) so re-scanning a page
 * of lines reuses the per-line query the mutant detail page already owns
 * instead of issuing a second request for the same data.
 */

import type { QueryClient } from "@tanstack/react-query";
import {
  getMutantLinePhenotypes,
  type MutantLineResponse,
  type PhenotypeResponse,
} from "@soymutdb/api-client";
import type { queryKeys as QueryKeys } from "@soymutdb/query-keys";

/** Lines read per scan step; the API caps `limit` at 200. */
export const PHENOTYPE_SCAN_LINE_LIMIT = 200;

/** Observations carried per line; the endpoint is unpaginated. */
export interface PhenotypeRow extends PhenotypeResponse {
  /** Public id of the line the observation belongs to (never the internal id). */
  line_public_id: string;
  line_name: string;
}

export interface PhenotypeScanResult {
  rows: PhenotypeRow[];
  /** Public lines the scan actually read. */
  linesScanned: number;
  /** True when the scan stopped before covering every public line. */
  truncated: boolean;
  /** How many lines the scan was allowed to read. */
  budget: number;
}

export interface PhenotypeScanInput {
  queryClient: QueryClient;
  keys: typeof QueryKeys;
  lines: readonly MutantLineResponse[];
  releaseId: string | null;
  siteVariant: "external" | "internal";
  /** Stop after this many lines (the budget the UI advertises). */
  lineBudget: number;
  /** Observation predicate applied after the per-line read. */
  matches: (row: PhenotypeRow) => boolean;
  signal?: AbortSignal;
}

/**
 * Read phenotype observations for the given lines, bounded by `lineBudget`.
 *
 * A line whose phenotype read fails contributes no rows and does not abort the
 * scan: one broken line must not blank the whole page. The failure is not
 * hidden either — `truncated` stays false only when every line in `lines` was
 * read successfully, so `failedLines` is what tells the caller to say so.
 */
export async function scanPhenotypes(
  input: PhenotypeScanInput,
): Promise<PhenotypeScanResult & { failedLines: number }> {
  const rows: PhenotypeRow[] = [];
  const seen = new Set<string>();
  let linesScanned = 0;
  let failedLines = 0;

  for (const line of input.lines) {
    if (linesScanned >= input.lineBudget) break;
    if (input.signal?.aborted) break;
    linesScanned += 1;
    let observations: PhenotypeResponse[];
    try {
      observations = await input.queryClient.ensureQueryData({
        queryKey: input.keys.mutants.phenotypes(
          line.public_id,
          input.releaseId,
          input.siteVariant,
        ),
        queryFn: () => getMutantLinePhenotypes(line.public_id),
      });
    } catch {
      failedLines += 1;
      continue;
    }
    for (const observation of observations ?? []) {
      const row: PhenotypeRow = {
        ...observation,
        // The line's public id is authoritative here: the observation carries
        // it too, but a partial payload must not produce a row that cannot be
        // traced back to a line.
        mutant_line_public_id: line.public_id,
        line_public_id: line.public_id,
        line_name: line.name,
      };
      if (!input.matches(row)) continue;
      // Observations have no public id of their own (`id` is the row key), so
      // dedupe on the tuple that identifies the observation inside a line.
      const key = [
        row.line_public_id,
        row.trait_category,
        row.trait_name,
        row.trait_value ?? "",
        row.unit ?? "",
        row.description ?? "",
      ].join("\u0000");
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push(row);
    }
  }

  return {
    rows,
    linesScanned,
    truncated: linesScanned < input.lines.length,
    budget: input.lineBudget,
    failedLines,
  };
}

/** Distinct trait categories present in a row set, sorted. */
export function traitCategories(rows: readonly PhenotypeRow[]): string[] {
  return [...new Set(rows.map((row) => row.trait_category).filter(Boolean))].sort();
}
