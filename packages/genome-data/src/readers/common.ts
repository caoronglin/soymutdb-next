import { assertAssembly, resolveRefName, type AssemblyContext } from "../assembly";
import { GenomeDataError, isAbortError, type GenomeDataErrorCode } from "../errors";
import type { Region } from "../types";

/** Options accepted by every region read. */
export interface ReadOptions {
  readonly signal?: AbortSignal;
}

/** A query region after assembly validation and reference name resolution. */
export interface ResolvedRegion {
  readonly refName: string;
  readonly start: number;
  readonly end: number;
}

/** Non-abort fallback codes used by readers when wrapping failures. */
export type ReaderErrorCode = Extract<GenomeDataErrorCode, "fetch" | "parse">;

function isAbortLike(error: unknown): boolean {
  if (isAbortError(error)) return true;
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { code?: unknown }).code === "ERR_ABORTED"
  );
}

/**
 * Map any thrown value onto the typed error surface.
 *
 * Existing GenomeDataError instances pass through so inner codes
 * (assembly-mismatch, parse, aborted) are preserved. Abort-like errors always
 * become "aborted" regardless of the fallback code, so the UI can silently
 * ignore cancellations.
 */
export function toGenomeDataError(
  error: unknown,
  fallbackCode: ReaderErrorCode,
  message: string,
  options?: { readonly trackId?: string },
): GenomeDataError {
  if (error instanceof GenomeDataError) return error;
  if (isAbortLike(error)) {
    return new GenomeDataError("aborted", message, {
      trackId: options?.trackId,
      cause: error,
    });
  }
  return new GenomeDataError(fallbackCode, message, {
    trackId: options?.trackId,
    cause: error,
  });
}

/**
 * Reject malformed query regions. Internal coordinates are 0-based half-open,
 * so start must be a non-negative integer and end must not precede it. An empty
 * region (start === end) is valid and reads return no records.
 */
export function assertValidRegion(region: Region, trackId?: string): void {
  const { start, end } = region;
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start
  ) {
    throw new GenomeDataError(
      "parse",
      `Invalid region ${region.refName}:${String(start)}-${String(end)}: ` +
        "expected 0-based half-open integers with 0 <= start <= end",
      { trackId },
    );
  }
}

/**
 * Enforce the assembly contract and resolve the reference name inside that
 * assembly. v4 and v5 are distinct namespaces, so a foreign assemblyKey or an
 * unknown reference name is always an assembly-mismatch, never a fallback.
 */
export function resolveRegion(
  assembly: AssemblyContext,
  region: Region,
  trackId?: string,
): ResolvedRegion {
  assertAssembly(assembly, region.assemblyKey);
  assertValidRegion(region, trackId);
  return {
    refName: resolveRefName(assembly, region.refName),
    start: region.start,
    end: region.end,
  };
}
