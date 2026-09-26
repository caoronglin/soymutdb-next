/**
 * Ruler tick math for the 0-based half-open viewport used by genome-view.
 *
 * Kept separate from @soymutdb/genome-view-model (which is 1-based inclusive)
 * so the browser's coordinate layer stays internally consistent.
 */
export interface RulerRegion {
  start: number;
  end: number;
}

export interface RulerTick {
  bp: number;
  x: number;
  label: string;
}

const NICE_STEPS = [1, 2, 5];

/** Smallest 1/2/5 x 10^n step that is >= rough. */
export function niceStep(rough: number): number {
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  for (const factor of NICE_STEPS) {
    const candidate = factor * magnitude;
    if (candidate >= rough) return candidate;
  }
  return 10 * magnitude;
}

/** Deterministic thousands grouping (avoids locale-dependent output). */
export function formatBp(bp: number): string {
  return String(Math.trunc(bp)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function computeTicks(
  region: RulerRegion,
  widthPx: number,
  targetPx = 80,
): RulerTick[] {
  const span = region.end - region.start;
  if (!Number.isFinite(span) || span <= 0) return [];
  if (!Number.isFinite(widthPx) || widthPx <= 0) return [];
  const target = targetPx > 0 ? targetPx : 80;
  const step = niceStep((span / widthPx) * target);
  const ticks: RulerTick[] = [];
  const first = Math.ceil(region.start / step) * step;
  for (let bp = first; bp <= region.end; bp += step) {
    ticks.push({ bp, x: ((bp - region.start) / span) * widthPx, label: formatBp(bp) });
    if (ticks.length > 1000) break;
  }
  return ticks;
}
