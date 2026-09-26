/**
 * Viewport and layout math for the genome view.
 *
 * Coordinates follow the rest of genome-view-model: 1-based inclusive
 * [start, end]. The deep-link/bridge boundary is the only place that converts
 * to/from 0-based half-open.
 *
 * Pure functions, zero dependencies.
 */
import { InvalidCoordinateError } from "./errors";

export interface Viewport {
  assemblyKey: string;
  refName: string;
  /** 1-based inclusive. */
  start: number;
  /** 1-based inclusive. */
  end: number;
}

export interface ViewportBounds {
  /** 1-based inclusive lower bound (usually 1). */
  start: number;
  /** 1-based inclusive upper bound (reference length). */
  end: number;
}

export const DEFAULT_MIN_BP = 40;

function assertPositiveInteger(value: number, label: string): void {
  if (!Number.isInteger(value) || value < 1) {
    throw new InvalidCoordinateError(label + " must be a positive integer, got " + value);
  }
}

function assertViewport(viewport: Viewport): void {
  assertPositiveInteger(viewport.start, "viewport.start");
  assertPositiveInteger(viewport.end, "viewport.end");
  if (viewport.start > viewport.end) {
    throw new InvalidCoordinateError(
      "viewport.start must not exceed end: [" + viewport.start + ", " + viewport.end + "]",
    );
  }
  if (!viewport.refName) {
    throw new InvalidCoordinateError("viewport must carry a non-empty refName");
  }
}

/** Number of bases in the 1-based inclusive viewport. */
export function viewportSpan(viewport: Viewport): number {
  assertViewport(viewport);
  return viewport.end - viewport.start + 1;
}

/** Keep the current width but slide/clip the window inside explicit bounds. */
export function clampViewport(
  viewport: Viewport,
  bounds: ViewportBounds,
  minBp: number = DEFAULT_MIN_BP,
): Viewport {
  assertViewport(viewport);
  assertPositiveInteger(bounds.start, "bounds.start");
  assertPositiveInteger(bounds.end, "bounds.end");
  if (bounds.start > bounds.end) {
    throw new InvalidCoordinateError("bounds.start must not exceed bounds.end");
  }
  const boundsSpan = bounds.end - bounds.start + 1;
  const width = Math.min(Math.max(viewportSpan(viewport), Math.min(minBp, boundsSpan)), boundsSpan);
  const maxStart = bounds.end - width + 1;
  const start = Math.min(Math.max(viewport.start, bounds.start), maxStart);
  return {
    assemblyKey: viewport.assemblyKey,
    refName: viewport.refName,
    start,
    end: start + width - 1,
  };
}

/**
 * Scale the viewport width. factor > 1 zooms out, < 1 zooms in. The anchor
 * (default: viewport centre) keeps its base under the same screen position.
 */
export function zoomViewport(
  viewport: Viewport,
  factor: number,
  anchorBp?: number,
  bounds?: ViewportBounds,
  minBp: number = DEFAULT_MIN_BP,
): Viewport {
  assertViewport(viewport);
  if (!Number.isFinite(factor) || factor <= 0) {
    throw new InvalidCoordinateError("zoom factor must be a positive number, got " + factor);
  }
  const span = viewportSpan(viewport);
  const anchor = anchorBp ?? viewport.start + (span - 1) / 2;
  let newSpan = Math.max(minBp, Math.round(span * factor));
  if (bounds) {
    newSpan = Math.min(newSpan, bounds.end - bounds.start + 1);
  }
  const offset = (anchor - viewport.start) * (newSpan / span);
  const start = Math.max(1, Math.round(anchor - offset));
  const next: Viewport = {
    assemblyKey: viewport.assemblyKey,
    refName: viewport.refName,
    start,
    end: start + newSpan - 1,
  };
  return bounds ? clampViewport(next, bounds, minBp) : next;
}

/** Shift the viewport by deltaBp (positive = towards higher coordinates). */
export function panViewport(
  viewport: Viewport,
  deltaBp: number,
  bounds?: ViewportBounds,
): Viewport {
  assertViewport(viewport);
  const next: Viewport = {
    assemblyKey: viewport.assemblyKey,
    refName: viewport.refName,
    start: Math.max(1, viewport.start + Math.round(deltaBp)),
    end: Math.max(1, viewport.end + Math.round(deltaBp)),
  };
  return bounds ? clampViewport(next, bounds) : next;
}

export function bpPerPx(viewport: Viewport, widthPx: number): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) {
    throw new InvalidCoordinateError("widthPx must be a positive number, got " + widthPx);
  }
  return viewportSpan(viewport) / widthPx;
}

export function toScreenX(bp: number, viewport: Viewport, widthPx: number): number {
  const span = viewportSpan(viewport);
  if (!Number.isFinite(widthPx) || widthPx <= 0) {
    throw new InvalidCoordinateError("widthPx must be a positive number, got " + widthPx);
  }
  return ((bp - viewport.start) / span) * widthPx;
}

export function toBp(x: number, viewport: Viewport, widthPx: number): number {
  const span = viewportSpan(viewport);
  if (!Number.isFinite(widthPx) || widthPx <= 0) {
    throw new InvalidCoordinateError("widthPx must be a positive number, got " + widthPx);
  }
  const bp = viewport.start + Math.floor((x / widthPx) * span);
  return Math.min(viewport.end, Math.max(viewport.start, bp));
}

export interface Interval {
  start: number;
  end: number;
}

/** Intersect an interval with the viewport; null when disjoint. */
export function clipInterval(interval: Interval, viewport: Viewport): Interval | null {
  assertViewport(viewport);
  assertPositiveInteger(interval.start, "interval.start");
  assertPositiveInteger(interval.end, "interval.end");
  const start = Math.max(interval.start, viewport.start);
  const end = Math.min(interval.end, viewport.end);
  if (start > end) return null;
  return { start, end };
}

const NICE_STEPS = [1, 2, 5];

function niceStep(rough: number): number {
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  for (const factor of NICE_STEPS) {
    const candidate = factor * magnitude;
    if (candidate >= rough) return candidate;
  }
  return 10 * magnitude;
}

export interface Tick {
  bp: number;
  x: number;
  label: string;
}

/** Ruler ticks at nice 1/2/5 x 10^n base steps. */
export function ticksFor(viewport: Viewport, widthPx: number, targetPx = 80): Tick[] {
  const span = viewportSpan(viewport);
  if (!Number.isFinite(widthPx) || widthPx <= 0) {
    throw new InvalidCoordinateError("widthPx must be a positive number, got " + widthPx);
  }
  const target = targetPx > 0 ? targetPx : 80;
  const step = niceStep((span / widthPx) * target);
  const ticks: Tick[] = [];
  const first = Math.ceil(viewport.start / step) * step;
  for (let bp = first; bp <= viewport.end; bp += step) {
    ticks.push({ bp, x: toScreenX(bp, viewport, widthPx), label: String(bp) });
    if (ticks.length > 1000) break;
  }
  return ticks;
}
