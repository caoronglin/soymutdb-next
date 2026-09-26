/** A resolvable genome data location: a URL or a local filesystem path. */
export type GenomeLocation =
  | { readonly kind: "uri"; readonly uri: string }
  | { readonly kind: "local"; readonly path: string };

export function uriLocation(uri: string): GenomeLocation {
  return { kind: "uri", uri };
}

export function localLocation(path: string): GenomeLocation {
  return { kind: "local", path };
}

/** Stable identity for handle caches; never depends on object identity. */
export function locationKey(location: GenomeLocation): string {
  return location.kind === "uri" ? "uri:" + location.uri : "local:" + location.path;
}
