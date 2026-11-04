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
 * ## Who does the scanning
 *
 * The page reads the per-line queries through `useQueries`, so each line read
 * reuses the query key the mutant detail page already owns instead of issuing a
 * second request for the same data. Only the pieces both the page and the row
 * model need live here; there is deliberately no imperative scan helper, because
 * nothing calls one (`knip` said so, correctly).
 */

import type { PhenotypeResponse } from "@soymutdb/api-client";

/** Lines read per scan step; the API caps `limit` at 200. */
export const PHENOTYPE_SCAN_LINE_LIMIT = 200;

/** Observations carried per line; the endpoint is unpaginated. */
export interface PhenotypeRow extends PhenotypeResponse {
  /** Public id of the line the observation belongs to (never the internal id). */
  line_public_id: string;
  line_name: string;
}

/** Distinct trait categories present in a row set, sorted. */
export function traitCategories(rows: readonly PhenotypeRow[]): string[] {
  return [...new Set(rows.map((row) => row.trait_category).filter(Boolean))].sort();
}
