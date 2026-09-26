/**
 * Pure screen layout for track rendering (0-based half-open coordinates).
 *
 * Kept framework-free so it can be unit-tested without a DOM and reused by the
 * SVG (feature/variant) and canvas (quantitative) renderers.
 */
export interface IntervalLike {
  id: string;
  start: number;
  end: number;
}

export interface RegionLike {
  start: number;
  end: number;
}

export interface PlacedInterval {
  id: string;
  x: number;
  w: number;
  row: number;
}

export interface LayoutResult {
  placed: PlacedInterval[];
  rowCount: number;
}

const MIN_WIDTH_PX = 1;

/** Intersect [start,end) with the region; null when disjoint or empty. */
export function clipToRegion(
  interval: { start: number; end: number },
  region: RegionLike,
): { start: number; end: number } | null {
  const start = Math.max(interval.start, region.start);
  const end = Math.min(interval.end, region.end);
  return end > start ? { start, end } : null;
}

/**
 * Greedy first-fit row packing in screen space. Input order is by genomic
 * position so the result is deterministic; overlapping labels never collide.
 */
export function layoutIntervals(
  intervals: readonly IntervalLike[],
  region: RegionLike,
  widthPx: number,
  options: { gapPx?: number; maxRows?: number } = {},
): LayoutResult {
  const span = region.end - region.start;
  if (!Number.isFinite(span) || span <= 0 || !Number.isFinite(widthPx) || widthPx <= 0) {
    return { placed: [], rowCount: 0 };
  }
  const gap = options.gapPx ?? 1;
  const maxRows = options.maxRows && options.maxRows > 0 ? options.maxRows : Number.POSITIVE_INFINITY;
  const scale = widthPx / span;
  const ordered = [...intervals]
    .filter((interval) => interval.end > interval.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const rowEnds: number[] = [];
  const placed: PlacedInterval[] = [];
  for (const interval of ordered) {
    const clipped = clipToRegion(interval, region);
    if (!clipped) continue;
    const x = (clipped.start - region.start) * scale;
    const w = Math.max(MIN_WIDTH_PX, (clipped.end - clipped.start) * scale);
    let row = rowEnds.findIndex((end) => x >= end + gap);
    if (row === -1) {
      if (rowEnds.length >= maxRows) continue;
      row = rowEnds.length;
      rowEnds.push(x + w);
    } else {
      rowEnds[row] = Math.max(rowEnds[row], x + w);
    }
    placed.push({ id: interval.id, x, w, row });
  }
  return { placed, rowCount: rowEnds.length };
}
