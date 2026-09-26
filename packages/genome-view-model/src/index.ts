/**
 * Framework-neutral genomic view-model (Phase C seam; consumed later by the
 * public portal and Admin Gene Preview).
 *
 * Encodes the biological-coordinate contracts from ``database-core-contract``:
 *
 *  - **Assembly-scoped** (DB-CORE-3 / H04): every interval carries its
 *    ``assemblyKey``. v4 and v5 are distinct namespaces, so operations that
 *    compare two intervals REFUSE to run across assemblies rather than silently
 *    collapsing them -- that is the whole point of the view-model.
 *  - **1-based, inclusive** coordinates (matching SoyMutDB extraction/seqfetch
 *    semantics): ``[start, end]`` with ``start <= end``; adjacent intervals
 *    ``[1,5]`` and ``[6,10]`` touch but do not overlap.
 *  - **Strand-aware**: strand is an explicit attribute and view packing/order
 *    respect it.
 *
 * Pure functions, zero dependencies, framework-agnostic.
 */

export type Strand = "+" | "-";

export interface GenomicInterval {
  /** Assembly/namespace this interval belongs to (e.g. "v4", "v5"). */
  assemblyKey: string;
  /** 1-based inclusive start. */
  start: number;
  /** 1-based inclusive end (>= start). */
  end: number;
}

export interface AnnotatedInterval extends GenomicInterval {
  strand: Strand;
}

/** Raised when an operation would compare intervals across assemblies. */
export class AssemblyMismatchError extends Error {
  constructor(left: string, right: string) {
    super(
      `refusing to compare intervals across assemblies: '${left}' vs '${right}' ` +
        "(assemblies are distinct namespaces; DB-CORE-3)",
    );
    this.name = "AssemblyMismatchError";
  }
}

/** Raised for malformed coordinates (non-integer, start > end, or < 1). */
export class InvalidCoordinateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidCoordinateError";
  }
}

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value >= 1;
}

export function assertValidInterval(interval: GenomicInterval): void {
  if (!isPositiveInteger(interval.start) || !isPositiveInteger(interval.end)) {
    throw new InvalidCoordinateError(
      `coordinates must be 1-based positive integers: got [${interval.start}, ${interval.end}]`,
    );
  }
  if (interval.start > interval.end) {
    throw new InvalidCoordinateError(
      `interval start must not exceed end: [${interval.start}, ${interval.end}]`,
    );
  }
  if (!interval.assemblyKey) {
    throw new InvalidCoordinateError("interval must carry a non-empty assemblyKey");
  }
}

/** Normalise an interval (swap reversed ends) after validating positivity. */
export function normalizeInterval(interval: GenomicInterval): GenomicInterval {
  const start = interval.start;
  const end = interval.end;
  if (!isPositiveInteger(start) || !isPositiveInteger(end)) {
    throw new InvalidCoordinateError(
      `coordinates must be 1-based positive integers: got [${start}, ${end}]`,
    );
  }
  return { assemblyKey: interval.assemblyKey, start: Math.min(start, end), end: Math.max(start, end) };
}

/** Length of a 1-based inclusive interval (>= 1). */
export function length(interval: GenomicInterval): number {
  assertValidInterval(interval);
  return interval.end - interval.start + 1;
}

export function sameAssembly(a: GenomicInterval, b: GenomicInterval): boolean {
  return a.assemblyKey === b.assemblyKey;
}

/** Do two intervals on the SAME assembly overlap (1-based inclusive)? */
export function overlaps(a: GenomicInterval, b: GenomicInterval): boolean {
  if (!sameAssembly(a, b)) {
    throw new AssemblyMismatchError(a.assemblyKey, b.assemblyKey);
  }
  return a.start <= b.end && b.start <= a.end;
}

/** Is ``inner`` fully contained within ``outer`` on the same assembly? */
export function contains(outer: GenomicInterval, inner: GenomicInterval): boolean {
  if (!sameAssembly(outer, inner)) {
    throw new AssemblyMismatchError(outer.assemblyKey, inner.assemblyKey);
  }
  return inner.start >= outer.start && inner.end <= outer.end;
}

/** Sort by ascending start, then ascending end (stable within ties). */
export function sortByPosition<T extends GenomicInterval>(intervals: readonly T[]): T[] {
  return [...intervals].sort((a, b) => a.start - b.start || a.end - b.end);
}

/** Clip an interval to a [winStart, winEnd] window; null when disjoint. */
export function clipToWindow(
  interval: GenomicInterval,
  winStart: number,
  winEnd: number,
): GenomicInterval | null {
  assertValidInterval({ assemblyKey: interval.assemblyKey, start: winStart, end: winEnd });
  const clipped: GenomicInterval = {
    assemblyKey: interval.assemblyKey,
    start: Math.max(interval.start, winStart),
    end: Math.min(interval.end, winEnd),
  };
  if (clipped.start > clipped.end) {
    return null;
  }
  return clipped;
}

export interface PackedItem<T> {
  item: T;
  row: number;
}

/**
 * Greedy row packing so overlapping intervals render on separate rows without
 * vertical collisions (the gene/transcript/exon packing used by the browser).
 *
 * Only operates within a single assembly: a mixed set throws rather than
 * silently packing across namespaces. Ordering is by ascending start then end,
 * and each item is placed in the lowest existing row whose last interval ends
 * before it begins; otherwise it opens a new row.
 */
export function packRows<T extends GenomicInterval>(intervals: readonly T[]): PackedItem<T>[][] {
  const assemblies = new Set(intervals.map((interval) => interval.assemblyKey));
  if (assemblies.size > 1) {
    throw new AssemblyMismatchError([...assemblies].join(", "), "<mixed>");
  }
  const rows: PackedItem<T>[][] = [];
  const rowLastEnd: number[] = [];
  for (const item of sortByPosition(intervals)) {
    assertValidInterval(item);
    const target = rowLastEnd.findIndex((lastEnd) => item.start > lastEnd);
    if (target === -1) {
      rows.push([{ item, row: rows.length }]);
      rowLastEnd.push(item.end);
    } else {
      rows[target].push({ item, row: target });
      rowLastEnd[target] = item.end;
    }
  }
  return rows;
}

/** Strand-aware ordering: group by strand ('+' before '-') then by position. */
export function sortForStrandView<T extends AnnotatedInterval>(
  intervals: readonly T[],
  strandFirst: Strand = "+",
): T[] {
  const rank = (s: Strand) => (s === strandFirst ? 0 : 1);
  return [...intervals].sort(
    (a, b) => rank(a.strand) - rank(b.strand) || a.start - b.start || a.end - b.end,
  );
}

export * from "./viewport";
