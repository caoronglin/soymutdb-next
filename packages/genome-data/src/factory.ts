import type { AssemblyContext } from "./assembly";
import { GenomeDataError } from "./errors";
import type { FileProvider } from "./file-provider";
import { localLocation, uriLocation, type GenomeLocation } from "./location";
import { FeatureReader } from "./readers/feature";
import { IntervalFeatureReader } from "./readers/interval";
import { QuantitativeReader } from "./readers/quantitative";
import { SequenceReader } from "./readers/sequence";
import { TextSearchReader } from "./readers/trix";
import { VariantReader } from "./readers/variant";
import type { TrackConfig } from "./types";

/** Options shared by every concrete reader the factory constructs. */
export interface CreateTrackDataSourceOptions {
  readonly provider: FileProvider;
  readonly assemblies: readonly AssemblyContext[];
}

interface TrackDataSourceBase {
  readonly trackId: string;
  readonly assemblyKey: string;
}

/** Discriminated union of everything the factory can build. */
export type TrackDataSource =
  | (TrackDataSourceBase & { readonly kind: "reference-sequence"; readonly reader: SequenceReader })
  | (TrackDataSourceBase & { readonly kind: "variant"; readonly reader: VariantReader })
  | (TrackDataSourceBase & { readonly kind: "feature"; readonly reader: FeatureReader })
  | (TrackDataSourceBase & { readonly kind: "interval"; readonly reader: IntervalFeatureReader })
  | (TrackDataSourceBase & { readonly kind: "quantitative"; readonly reader: QuantitativeReader });

export type TrackDataSourceKind = TrackDataSource["kind"];

type AdapterConfig = Readonly<Record<string, unknown>>;

function unsupported(trackId: string, message: string): GenomeDataError {
  return new GenomeDataError("unsupported-type", message, { trackId });
}

function readAdapter(track: TrackConfig): AdapterConfig {
  const adapter = track.adapter;
  if (!adapter || typeof adapter !== "object") {
    throw unsupported(track.trackId, "Track \"" + track.trackId + "\" has no adapter configuration");
  }
  return adapter;
}

function adapterType(adapter: AdapterConfig): string | undefined {
  return typeof adapter.type === "string" ? adapter.type : undefined;
}

function requireAdapterType(
  track: TrackConfig,
  adapter: AdapterConfig,
  accepted: readonly string[],
): string {
  const type = adapterType(adapter);
  if (!type || !accepted.includes(type)) {
    throw unsupported(
      track.trackId,
      "Track \"" + track.trackId + "\" adapter \"" + (type ?? "(none)") + "\" is not supported; expected " + accepted.join(" or "),
    );
  }
  return type;
}

/** Accept a JBrowse file location, an index wrapper, or a bare URI string. */
function asLocation(value: unknown, label: string, trackId: string): GenomeLocation {
  if (typeof value === "string") return uriLocation(value);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.uri === "string") return uriLocation(record.uri);
    if (typeof record.localPath === "string") return localLocation(record.localPath);
    if (record.location !== undefined) {
      return asLocation(record.location, label, trackId);
    }
  }
  throw unsupported(trackId, "Track \"" + trackId + "\" is missing the " + label + " location");
}

function requireLocation(
  adapter: AdapterConfig,
  key: string,
  trackId: string,
): GenomeLocation {
  return asLocation(adapter[key], key, trackId);
}

function resolveAssembly(
  track: TrackConfig,
  assemblies: readonly AssemblyContext[],
): AssemblyContext {
  for (const assemblyName of track.assemblyNames) {
    const found = assemblies.find(
      (assembly) => assembly.key === assemblyName || assembly.name === assemblyName,
    );
    if (found) return found;
  }
  throw new GenomeDataError(
    "assembly-mismatch",
    "Track \"" + track.trackId + "\" references an unknown assembly: " +
      (track.assemblyNames.join(", ") || "(none)"),
    { trackId: track.trackId },
  );
}

/**
 * Build the reader for a backend track definition.
 *
 * Dispatch is by track.type; FeatureTrack additionally inspects the adapter so
 * both GFF3 (tabix) and bigBed feature tracks are covered. Unknown or
 * not-yet-implemented types throw a GenomeDataError("unsupported-type") so the
 * UI can hide the track instead of failing the whole view.
 */
export function createTrackDataSource(
  track: TrackConfig,
  options: CreateTrackDataSourceOptions,
): TrackDataSource {
  const assembly = resolveAssembly(track, options.assemblies);
  const base = { trackId: track.trackId, assemblyKey: assembly.key };
  switch (track.type) {
    case "ReferenceSequenceTrack": {
      const adapter = readAdapter(track);
      requireAdapterType(track, adapter, ["BgzipFastaAdapter"]);
      return {
        ...base,
        kind: "reference-sequence",
        reader: new SequenceReader({
          provider: options.provider,
          assembly,
          trackId: track.trackId,
          fasta: requireLocation(adapter, "fastaLocation", track.trackId),
          fai: requireLocation(adapter, "faiLocation", track.trackId),
          gzi: requireLocation(adapter, "gziLocation", track.trackId),
        }),
      };
    }
    case "VariantTrack": {
      const adapter = readAdapter(track);
      requireAdapterType(track, adapter, ["VcfTabixAdapter"]);
      return {
        ...base,
        kind: "variant",
        reader: new VariantReader({
          provider: options.provider,
          assembly,
          trackId: track.trackId,
          vcf: requireLocation(adapter, "vcfGzLocation", track.trackId),
          index: asLocation(adapter.index, "index", track.trackId),
        }),
      };
    }
    case "FeatureTrack": {
      const adapter = readAdapter(track);
      const type = adapterType(adapter);
      if (type === "Gff3TabixAdapter") {
        return {
          ...base,
          kind: "feature",
          reader: new FeatureReader({
            provider: options.provider,
            assembly,
            trackId: track.trackId,
            gff: requireLocation(adapter, "gffGzLocation", track.trackId),
            index: asLocation(adapter.index, "index", track.trackId),
          }),
        };
      }
      if (type === "BigBedAdapter") {
        return {
          ...base,
          kind: "interval",
          reader: new IntervalFeatureReader({
            provider: options.provider,
            assembly,
            trackId: track.trackId,
            bigBed: requireLocation(adapter, "bigBedLocation", track.trackId),
          }),
        };
      }
      throw unsupported(
        track.trackId,
        "FeatureTrack \"" + track.trackId + "\" adapter \"" + (type ?? "(none)") + "\" is not supported; expected Gff3TabixAdapter or BigBedAdapter",
      );
    }
    case "QuantitativeTrack": {
      const adapter = readAdapter(track);
      requireAdapterType(track, adapter, ["BigWigAdapter"]);
      return {
        ...base,
        kind: "quantitative",
        reader: new QuantitativeReader({
          provider: options.provider,
          assembly,
          trackId: track.trackId,
          bigWig: requireLocation(adapter, "bigWigLocation", track.trackId),
        }),
      };
    }
    case "AlignmentsTrack":
      throw unsupported(
        track.trackId,
        "AlignmentsTrack is not implemented yet (track \"" + track.trackId + "\")",
      );
    default:
      throw unsupported(
        track.trackId,
        "Unsupported track type \"" + track.type + "\" (track \"" + track.trackId + "\")",
      );
  }
}

/** JBrowse-shaped Trix text-search adapter (an aggregateTextSearchAdapters entry). */
export interface TextSearchAdapterConfig {
  readonly textSearchAdapterId: string;
  readonly ixFilePath: unknown;
  readonly ixxFilePath: unknown;
  readonly assemblyNames?: readonly string[];
}

/** A text-search reader bound to exactly one assembly. */
export interface TextSearchDataSource {
  readonly sourceId: string;
  readonly assemblyKey: string;
  readonly reader: TextSearchReader;
}

function resolveTextSearchAssembly(
  adapter: TextSearchAdapterConfig,
  assemblies: readonly AssemblyContext[],
): AssemblyContext {
  const names = adapter.assemblyNames ?? [];
  for (const name of names) {
    const found = assemblies.find(
      (assembly) => assembly.key === name || assembly.name === name,
    );
    if (found) return found;
  }
  throw new GenomeDataError(
    "assembly-mismatch",
    "Text-search adapter \"" + adapter.textSearchAdapterId +
      "\" references an unknown assembly: " + (names.join(", ") || "(none)"),
  );
}

/**
 * Build an assembly-scoped text-search source from a configured adapter.
 *
 * Selection is explicit: the adapter must name an assembly present in
 * `options.assemblies`; there is no implicit "first adapter" fallback. The
 * returned reader owns its .ix/.ixx locations, and the assembly identity is
 * surfaced so callers can label or scope results.
 */
export function createTextSearchDataSource(
  adapter: TextSearchAdapterConfig,
  options: CreateTrackDataSourceOptions,
): TextSearchDataSource {
  const assembly = resolveTextSearchAssembly(adapter, options.assemblies);
  return {
    sourceId: adapter.textSearchAdapterId,
    assemblyKey: assembly.key,
    reader: new TextSearchReader({
      provider: options.provider,
      trackId: adapter.textSearchAdapterId,
      ix: asLocation(adapter.ixFilePath, "ixFilePath", adapter.textSearchAdapterId),
      ixx: asLocation(adapter.ixxFilePath, "ixxFilePath", adapter.textSearchAdapterId),
    }),
  };
}
