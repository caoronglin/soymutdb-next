/** Pure mapping of ReleaseResponse payloads to management table rows.
 * Active status comes from /releases/active; publication dates use published_at.
 * Network requests and view state belong to the route component.
 */

/** `ReleaseStatus` in `apps/api/app/models/content.py`. */
export const RELEASE_STATUSES = ["draft", "validated", "ready", "published", "rolled_back"] as const;

export type ReleaseStatus = (typeof RELEASE_STATUSES)[number];

export interface ReleaseRow {
  id: string;
  /** `ReleaseResponse.version`; empty when the payload omits it. */
  version: string;
  name: string;
  description: string | null;
  /** Kept as a string so an unrecognised status renders verbatim instead of being coerced. */
  status: string;
  variantCount: number;
  geneCount: number;
  mutantLineCount: number;
  /** `ReleaseResponse.published_at`; null before the first publish. */
  publishedAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  /** Derived from `/releases/active`, never from a list field. */
  isActive: boolean;
}

export function isReleaseStatus(value: unknown): value is ReleaseStatus {
  return typeof value === "string" && (RELEASE_STATUSES as readonly string[]).includes(value);
}

/** AntD tag tone per status; unknown statuses stay neutral rather than guessing. */
export function statusTone(status: string): string {
  if (status === "published") return "green";
  if (status === "ready" || status === "validated") return "blue";
  if (status === "rolled_back") return "orange";
  return "default";
}

function readString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function readCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return 0;
  return Math.trunc(value);
}

/** Keep only timestamps a `Date` can actually parse, so no "Invalid Date" reaches the table. */
function readTimestamp(value: unknown): string | null {
  const raw = readString(value);
  if (raw === null || raw === "" || Number.isNaN(Date.parse(raw))) return null;
  return raw;
}

/**
 * Map one `ReleaseResponse` payload to a row, or `null` when the payload cannot
 * carry a row identity. The id is the table's `rowKey`, so a payload without a
 * usable one is dropped rather than rendered as an unkeyed row.
 */
export function toReleaseRow(payload: unknown, activeReleaseId: string | null = null): ReleaseRow | null {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return null;
  const raw = payload as Record<string, unknown>;
  const id = readString(raw.id);
  if (id === null || id === "") return null;
  return {
    id,
    version: readString(raw.version) ?? "",
    name: readString(raw.name) ?? "",
    description: readString(raw.description),
    status: readString(raw.status) ?? "",
    variantCount: readCount(raw.variant_count),
    geneCount: readCount(raw.gene_count),
    mutantLineCount: readCount(raw.mutant_line_count),
    publishedAt: readTimestamp(raw.published_at),
    createdAt: readTimestamp(raw.created_at),
    updatedAt: readTimestamp(raw.updated_at),
    isActive: activeReleaseId !== null && activeReleaseId === id,
  };
}

/** Map the `list[ReleaseResponse]` payload; unusable entries are dropped, not crashed on. */
export function toReleaseRows(payload: unknown, activeReleaseId: string | null = null): ReleaseRow[] {
  if (!Array.isArray(payload)) return [];
  const rows: ReleaseRow[] = [];
  for (const item of payload) {
    const row = toReleaseRow(item, activeReleaseId);
    if (row !== null) rows.push(row);
  }
  return rows;
}

/**
 * Read `ActiveReleaseResponse.release_id`. Both fields are null before the first
 * publish; that is an answer, not an error, so it maps to `null` and the page
 * simply renders no active badge.
 */
export function readActiveReleaseId(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return null;
  const releaseId = readString((payload as Record<string, unknown>).release_id);
  return releaseId === null || releaseId === "" ? null : releaseId;
}
