/**
 * Typed error surface for genome data access.
 *
 * Every reader failure is mapped to a stable code so the UI can decide between
 * "hide this track" (unsupported-type), "show an inline error" (fetch/parse) and
 * "silently ignore" (aborted). Never leak raw parser or network errors upward.
 */
export type GenomeDataErrorCode =
  | "fetch"
  | "parse"
  | "unsupported-type"
  | "assembly-mismatch"
  | "aborted";

export class GenomeDataError extends Error {
  readonly code: GenomeDataErrorCode;
  readonly trackId?: string;

  constructor(
    code: GenomeDataErrorCode,
    message: string,
    options?: { trackId?: string; cause?: unknown },
  ) {
    super(message, options && "cause" in options ? { cause: options.cause } : undefined);
    this.name = "GenomeDataError";
    this.code = code;
    this.trackId = options?.trackId;
  }
}

export function isGenomeDataError(value: unknown): value is GenomeDataError {
  return value instanceof GenomeDataError;
}

export function isAbortError(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { name?: unknown }).name === "AbortError"
  );
}
