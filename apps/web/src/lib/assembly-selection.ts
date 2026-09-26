/**
 * Assembly selection for URL-backed state.
 *
 * The portal's canonical assembly identity is the stable numeric ``id``; deep
 * links, cache keys and request context all carry it. Genome labels (name and
 * version) are display and request-boundary concerns only:
 *
 * - a *name* may match several assemblies (v4/v5 share "Wm82"), so a
 *   name-only parameter is resolved on a best-effort basis and reported as
 *   ambiguous rather than silently collapsed onto the first match;
 * - an unknown parameter is reported instead of falling back to the default
 *   assembly, because querying another namespace returns plausible-looking
 *   results for the wrong genome.
 */
import type { AssemblyInfo } from "@soymutdb/api-client";

export type AssemblyResolution =
  | { status: "absent" }
  | { status: "resolved"; assembly: AssemblyInfo; via: "id" | "name" }
  | { status: "unknown" }
  | { status: "ambiguous"; matches: AssemblyInfo[] };

/** Resolve a URL parameter (stable id first, then legacy name). */
export function resolveAssemblyParam(
  assemblies: readonly AssemblyInfo[],
  raw: string | null | undefined,
): AssemblyResolution {
  const value = (raw ?? "").trim();
  if (!value) return { status: "absent" };

  const byId = assemblies.find((assembly) => String(assembly.id) === value);
  if (byId) return { status: "resolved", assembly: byId, via: "id" };

  const byName = assemblies.filter((assembly) => assembly.name === value);
  if (byName.length === 1) return { status: "resolved", assembly: byName[0]!, via: "name" };
  if (byName.length > 1) return { status: "ambiguous", matches: byName };

  return { status: "unknown" };
}

/**
 * Display label that keeps v4/v5 distinguishable: name alone repeats across
 * versions, so the version is always part of the visible option text.
 */
export function assemblyOptionLabel(assembly: AssemblyInfo): string {
  const version = assembly.version?.trim();
  return version ? `${assembly.name} ${version}` : assembly.name;
}
