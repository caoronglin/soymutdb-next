import { resolveAssemblyParam } from "./assembly-selection";

export interface SearchAssembly {
  id: number | string;
  name: string;
  is_default?: boolean;
}

/** Explicit links use the canonical id/unique-name resolver; only an absent link may use a default. */
export function resolveSearchAssembly<T extends SearchAssembly>(
  assemblies: readonly T[] | undefined,
  requested?: string,
): T | undefined {
  if (requested) {
    const resolution = resolveAssemblyParam(assemblies ?? [], requested);
    return resolution.status === "resolved" ? resolution.assembly : undefined;
  }
  return assemblies?.find((assembly) => assembly.is_default) ?? assemblies?.[0];
}
