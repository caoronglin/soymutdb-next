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

export type AssemblyResolution<T extends Pick<AssemblyInfo, "id" | "name"> = AssemblyInfo> =
  | { status: "absent" }
  | { status: "resolved"; assembly: T; via: "id" | "name" }
  | { status: "unknown" }
  | { status: "ambiguous"; matches: T[] };

/** Resolve a URL parameter (stable id first, then legacy name). */
export function resolveAssemblyParam<T extends Pick<AssemblyInfo, "id" | "name">>(
  assemblies: readonly T[],
  raw: string | null | undefined,
): AssemblyResolution<T> {
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

/**
 * The numeric id an API request can carry.
 *
 * The catalogue types `id` as `string | number`, but the detail and search
 * endpoints take an integer: sending a non-numeric id produces a 422, so an
 * unresolvable id is reported here and the caller declines to query rather
 * than sending a value the endpoint cannot read.
 */
export function toAssemblyIdParam(raw: string | number): number | undefined {
  const value = typeof raw === "number" ? raw : Number(String(raw).trim());
  return Number.isInteger(value) && value >= 1 ? value : undefined;
}
