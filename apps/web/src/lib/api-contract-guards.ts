/**
 * Runtime guards for API payloads that drive coordinate rendering.
 *
 * The api-client's generated types are a build-time contract, not a runtime
 * one: a proxy, a stale deployment or an offline fixture can return a valid JSON
 * document of the wrong shape. On the gene detail page that turned into a render
 * crash — a search-list envelope (`{items: []}`) arrived where `GeneDetail` was
 * expected, the page treated it as a gene, and the genome view read
 * `start_pos.toLocaleString()` off `undefined`.
 *
 * The guard checks only the fields that make a record usable for rendering
 * coordinates; everything else stays optional and degrades to the empty state.
 */
import type { GeneDetail, MutantLineDetail, NewsDetail } from "@soymutdb/api-client";

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** True when `value` is structurally usable as a `GeneDetail` render record. */
export function isGeneDetailRecord(value: unknown): value is GeneDetail {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.gene_id === "string" &&
    record.gene_id.length > 0 &&
    typeof record.chromosome === "string" &&
    record.chromosome.length > 0 &&
    isFiniteNumber(record.start_pos) &&
    isFiniteNumber(record.end_pos) &&
    record.end_pos >= record.start_pos
  );
}


/**
 * Mutant-line detail guard. Same failure mode as the gene page: a list/page
 * envelope or a `{error: ...}` body can arrive with HTTP 200 from a proxy or a
 * stale fixture; the detail page then renders `line.public_id`/`line.name`.
 */
export function isMutantLineDetailRecord(value: unknown): value is MutantLineDetail {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.public_id === "string" &&
    record.public_id.length > 0 &&
    typeof record.name === "string" &&
    typeof record.species === "string"
  );
}

/**
 * News-detail guard. Requires the bilingual title/body fields the page renders;
 * a list envelope (`{items: []}`) or an error body must fall through to the
 * not-found/error Result instead of rendering `undefined` fields.
 */
export function isNewsDetailRecord(value: unknown): value is NewsDetail {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.slug === "string" &&
    record.slug.length > 0 &&
    typeof record.title_en === "string" &&
    typeof record.content_en === "string"
  );
}
