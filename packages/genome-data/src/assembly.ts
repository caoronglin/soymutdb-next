import { GenomeDataError } from "./errors";

/**
 * Assembly-scoped context. v4 and v5 are distinct coordinate/identifier
 * namespaces, so every read resolves its reference name inside exactly one
 * assembly and never falls back to a cross-assembly guess.
 */
export interface AssemblyContext {
  /** Stable assembly key used in records and cache keys. */
  readonly key: string;
  /** Human/display name (may also be used as a reference name). */
  readonly name: string;
  readonly aliases?: readonly string[];
  /** Canonical reference (chromosome/scaffold) names for this assembly. */
  readonly refNames?: readonly string[];
  /** Alternate reference name -> canonical reference name. */
  readonly refNameAliases?: Readonly<Record<string, string>>;
}

export function resolveRefName(assembly: AssemblyContext, refName: string): string {
  const trimmed = refName.trim();
  if (!trimmed) {
    throw new GenomeDataError(
      "assembly-mismatch",
      "A reference name is required to read assembly " + assembly.key,
    );
  }
  if (assembly.refNames?.includes(trimmed)) return trimmed;
  const mapped = assembly.refNameAliases?.[trimmed];
  if (mapped) return mapped;
  throw new GenomeDataError(
    "assembly-mismatch",
    'Unknown reference "' + trimmed + '" for assembly "' + assembly.key + '"',
  );
}

export function assertAssembly(assembly: AssemblyContext, assemblyKey: string): void {
  if (assembly.key !== assemblyKey) {
    throw new GenomeDataError(
      "assembly-mismatch",
      'Record assembly "' + assemblyKey + '" does not match "' + assembly.key + '"',
    );
  }
}
