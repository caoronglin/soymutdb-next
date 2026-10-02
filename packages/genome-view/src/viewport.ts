/**
 * Genome viewport over an assembly-scoped reference window.
 *
 * Coordinates follow the `Region` contract from `@soymutdb/genome-data`:
 * 0-based, half-open (`start` inclusive, `end` exclusive).
 *
 * The arithmetic is deliberately written as pure functions over a plain data
 * object, with a thin React hook on top. That keeps the geometry usable outside
 * a browser — the pre-rendered SVG route builds the exact same picture in Node,
 * so the static artifact and the interactive view cannot drift apart.
 */
import { useCallback, useMemo, useState } from "react";
import type { Region } from "@soymutdb/genome-data";

/** Smallest window the viewport will ever hold, in base pairs. */
export const MIN_SPAN = 1;

/** Immutable window state; pan/zoom/goto return a new value. */
export interface GenomeViewport {
  /** Stable assembly key; v4 and v5 are distinct coordinate namespaces. */
  assemblyKey: string;
  /** Reference sequence name within the current assembly. */
  refName: string;
  /** 0-based inclusive window start. */
  start: number;
  /** 0-based exclusive window end. */
  end: number;
}

/** Actions returned alongside the current viewport state. */
export interface GenomeViewportActions {
  /** Shift the window by `deltaBp`, keeping its span and clamping at 0. */
  pan(deltaBp: number): void;
  /** Scale the window width by `factor`, keeping `anchorBp` (default: centre) fixed. */
  zoom(factor: number, anchorBp?: number): void;
  /** Jump to an explicit locus; reversed ends are normalised. */
  gotoLocus(refName: string, start: number, end: number): void;
  /** Replace the whole window, e.g. when the assembly changes. */
  reset(next: Region): void;
}

function toInteger(value: number, fallback: number): number {
  return Number.isFinite(value) ? Math.trunc(value) : fallback;
}

/** Build a normalised viewport from an initial `Region`. */
export function createViewport(initial: Region): GenomeViewport {
  const start = toInteger(initial.start, 0);
  const end = Math.max(toInteger(initial.end, start + MIN_SPAN), start + MIN_SPAN);
  return {
    assemblyKey: initial.assemblyKey,
    refName: initial.refName,
    start,
    end,
  };
}

/** Shift the window by `deltaBp`, keeping its span and clamping start at 0. */
export function panViewport(viewport: GenomeViewport, deltaBp: number): GenomeViewport {
  if (!Number.isFinite(deltaBp)) {
    return viewport;
  }
  const span = viewport.end - viewport.start;
  const nextStart = Math.max(0, viewport.start + Math.trunc(deltaBp));
  return { ...viewport, start: nextStart, end: nextStart + span };
}

/** Scale the window width by `factor`, keeping `anchorBp` (default: centre) fixed. */
export function zoomViewport(
  viewport: GenomeViewport,
  factor: number,
  anchorBp?: number,
): GenomeViewport {
  if (!Number.isFinite(factor) || factor <= 0) {
    return viewport;
  }
  const span = viewport.end - viewport.start;
  const anchor =
    anchorBp !== undefined && Number.isFinite(anchorBp)
      ? anchorBp
      : viewport.start + span / 2;
  const fraction = (anchor - viewport.start) / span;
  const nextSpan = Math.max(MIN_SPAN, Math.round(span * factor));
  const nextStart = Math.max(0, Math.round(anchor - fraction * nextSpan));
  return { ...viewport, start: nextStart, end: nextStart + nextSpan };
}

/** Jump to an explicit locus; reversed ends are normalised. */
export function gotoViewport(
  viewport: GenomeViewport,
  refName: string,
  startBp: number,
  endBp: number,
): GenomeViewport {
  const a = toInteger(startBp, 0);
  const b = toInteger(endBp, a + MIN_SPAN);
  const nextStart = Math.max(0, Math.min(a, b));
  return {
    ...viewport,
    refName,
    start: nextStart,
    end: Math.max(a, b, nextStart + MIN_SPAN),
  };
}

/** Base pairs per rendered pixel for a viewport `widthPx` pixels wide. */
export function bpPerPx(viewport: GenomeViewport, widthPx: number): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) {
    return 0;
  }
  return (viewport.end - viewport.start) / widthPx;
}

/** Convert a base-pair coordinate to an x offset inside a `widthPx`-wide track. */
export function bpToPx(viewport: GenomeViewport, bp: number, widthPx: number): number {
  const scale = bpPerPx(viewport, widthPx);
  if (scale === 0) {
    return 0;
  }
  return (bp - viewport.start) / scale;
}

/** React hook wrapping the pure viewport functions. */
export function useGenomeViewport(initial: Region): {
  viewport: GenomeViewport;
  actions: GenomeViewportActions;
} {
  const [state, setState] = useState<GenomeViewport>(() => createViewport(initial));

  const actions = useMemo<GenomeViewportActions>(
    () => ({
      pan: (deltaBp) => setState((current) => panViewport(current, deltaBp)),
      zoom: (factor, anchorBp) =>
        setState((current) => zoomViewport(current, factor, anchorBp)),
      gotoLocus: (refName, start, end) =>
        setState((current) => gotoViewport(current, refName, start, end)),
      reset: (next) => setState(createViewport(next)),
    }),
    [],
  );

  return { viewport: state, actions };
}

/** Stable identity for a viewport, useful as a cache key. */
export function viewportKey(viewport: GenomeViewport): string {
  return `${viewport.assemblyKey}:${viewport.refName}:${viewport.start}-${viewport.end}`;
}

/** Referentially stable callback for consumers that memoise on the window. */
export function useViewportKey(viewport: GenomeViewport): string {
  return useMemo(() => viewportKey(viewport), [viewport]);
}

/** Identity helper kept so callers can depend on a stable function reference. */
export function useStableViewportCallback(
  callback: (viewport: GenomeViewport) => void,
): (viewport: GenomeViewport) => void {
  return useCallback((viewport: GenomeViewport) => callback(viewport), [callback]);
}
