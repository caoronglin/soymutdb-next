export interface SearchAssembly {
  id: number | string;
  name: string;
  is_default?: boolean;
}

/** A deep link with an unknown assembly must not silently search the default assembly. */
export function resolveSearchAssembly<T extends SearchAssembly>(
  assemblies: readonly T[] | undefined,
  requested?: string,
): T | undefined {
  if (requested) {
    return assemblies?.find((assembly) =>
      String(assembly.id) === requested || assembly.name === requested,
    );
  }
  return assemblies?.find((assembly) => assembly.is_default) ?? assemblies?.[0];
}
