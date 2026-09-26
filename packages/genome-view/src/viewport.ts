/**
 * Reactive genome viewport over an assembly-scoped reference window.
 *
 * Coordinates follow the `Region` contract from `@soymutdb/genome-data`:
 * 0-based, half-open (`start` inclusive, `end` exclusive). The pan/zoom
 * arithmetic lives here on purpose so this package has no runtime dependency on
 * the concurrently evolving `@soymutdb/genome-view-model`.
 */
import { reactive } from "vue";
import type { Region } from "@soymutdb/genome-data";

/** Smallest window the viewport will ever hold, in base pairs. */
const MIN_SPAN = 1;

/** Shift window by delta; clamp start at 0. */
export interface GenomeViewport {
  /** Stable assembly key; v4 and v5 are distinct coordinate namespaces. */
  assemblyKey: string;
  /** Reference sequence name within the current assembly. */
  refName: string;
  /** 0-based inclusive window start. */
  start: number;
  /** 0-based exclusive window end. */
  end: number;
  /** Shift the window by `deltaBp`, keeping its span and clamping at 0. */
  pan(deltaBp: number): void;
  /** Scale the window width by `factor`, keeping `anchorBp` (default: centre) fixed. */
  zoom(factor: number, anchorBp?: number): void;
  /** Jump to an explicit locus; reversed ends are normalised. */
  gotoLocus(refName: string, start: number, end: number): void;
  /** Base pairs per rendered pixel for a viewport `widthPx` pixels wide. */
  bpPerPx(widthPx: number): number;
}

function toInteger(value: number, fallback: number): number {
  return Number.isFinite(value) ? Math.trunc(value) : fallback;
}

/**
 * Create a reactive viewport from an initial `Region`.
 *
 * The returned object is deeply reactive: mutating it through the actions below
 * (or reading `start`/`end` in effects) tracks correctly.
 */
export function useGenomeViewport(initial: Region): GenomeViewport {
  const initialStart = toInteger(initial.start, 0);
  const initialEnd = Math.max(
    toInteger(initial.end, initialStart + MIN_SPAN),
    initialStart + MIN_SPAN,
  );

  const viewport = reactive<GenomeViewport>({
    assemblyKey: initial.assemblyKey,
    refName: initial.refName,
    start: initialStart,
    end: initialEnd,
    pan(deltaBp: number): void {
      if (!Number.isFinite(deltaBp)) {
        return;
      }
      const span = viewport.end - viewport.start;
      const nextStart = Math.max(0, viewport.start + Math.trunc(deltaBp));
      viewport.start = nextStart;
      viewport.end = nextStart + span;
    },
    zoom(factor: number, anchorBp?: number): void {
      if (!Number.isFinite(factor) || factor <= 0) {
        return;
      }
      const span = viewport.end - viewport.start;
      const anchor =
        anchorBp !== undefined && Number.isFinite(anchorBp)
          ? anchorBp
          : viewport.start + span / 2;
      const fraction = (anchor - viewport.start) / span;
      const nextSpan = Math.max(MIN_SPAN, Math.round(span * factor));
      const nextStart = Math.max(0, Math.round(anchor - fraction * nextSpan));
      viewport.start = nextStart;
      viewport.end = nextStart + nextSpan;
    },
    gotoLocus(refName: string, startBp: number, endBp: number): void {
      const a = toInteger(startBp, 0);
      const b = toInteger(endBp, a + MIN_SPAN);
      const nextStart = Math.max(0, Math.min(a, b));
      viewport.refName = refName;
      viewport.start = nextStart;
      viewport.end = Math.max(a, b, nextStart + MIN_SPAN);
    },
    bpPerPx(widthPx: number): number {
      if (!Number.isFinite(widthPx) || widthPx <= 0) {
        return 0;
      }
      return (viewport.end - viewport.start) / widthPx;
    },
  });

  return viewport;
}
