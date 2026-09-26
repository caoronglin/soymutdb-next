import { BigBed, type Feature as BbiFeature } from "@gmod/bbi";

import type { AssemblyContext } from "../assembly";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { FeatureRecord, Region } from "../types";
import { resolveRegion, throwIfAborted, toGenomeDataError, type ReadOptions } from "./common";

export interface IntervalFeatureReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly bigBed: GenomeLocation;
  readonly trackId?: string;
  /** Value stored on FeatureRecord.type when the BigBed has no type column. */
  readonly featureType?: string;
}

/** The conventional columns of a bigBed "rest" payload. */
export interface BigBedRestFields {
  readonly name?: string;
  readonly score?: number;
  readonly strand?: "+" | "-" | ".";
  readonly fields: readonly string[];
}

/** Split the space-separated rest payload of a bigBed feature. */
export function parseBigBedRest(rest?: string): BigBedRestFields {
  const fields = rest ? rest.split(/\s+/).filter((field) => field !== "") : [];
  const rawScore = fields[1];
  const score = rawScore === undefined ? undefined : Number(rawScore);
  const rawStrand = fields[2];
  const strand = rawStrand === "+" || rawStrand === "-" ? rawStrand : undefined;
  return {
    ...(fields[0] ? { name: fields[0] } : {}),
    ...(score === undefined || Number.isNaN(score) ? {} : { score }),
    ...(strand ? { strand } : {}),
    fields,
  };
}

/**
 * Normalize raw BigBed features. BigBed spans are already 0-based half-open and
 * the rest payload carries the remaining BED columns.
 */
export function normalizeBigBedFeatures(
  features: readonly BbiFeature[],
  options: {
    readonly assemblyKey: string;
    readonly refName: string;
    readonly featureType: string;
  },
): FeatureRecord[] {
  return features.map((feature) => {
    const bed = parseBigBedRest(feature.rest);
    return {
      assemblyKey: options.assemblyKey,
      refName: options.refName,
      start: feature.start,
      end: feature.end,
      id:
        feature.uniqueId ??
        bed.name ??
        `${options.refName}:${String(feature.start)}-${String(feature.end)}`,
      type: options.featureType,
      ...(bed.name === undefined ? {} : { name: bed.name }),
      ...(bed.strand === undefined ? {} : { strand: bed.strand }),
      ...(bed.score === undefined ? {} : { score: bed.score }),
      ...(feature.rest === undefined ? {} : { attributes: { rest: feature.rest } }),
    };
  });
}

/** Reads bigBed interval/repeat tracks through @gmod/bbi. */
export class IntervalFeatureReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private readonly featureType: string;
  private bigBed?: Promise<BigBed>;

  constructor(private readonly options: IntervalFeatureReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
    this.featureType = options.featureType ?? "feature";
  }

  private getBigBed(): Promise<BigBed> {
    this.bigBed ??= this.openBigBed();
    return this.bigBed;
  }

  private async openBigBed(): Promise<BigBed> {
    const { provider, bigBed } = this.options;
    try {
      const handle = await provider.open(bigBed);
      return new BigBed({ filehandle: handle });
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open BigBed file", {
        trackId: this.trackId,
      });
    }
  }

  async getFeatures(
    region: Region,
    options: ReadOptions = {},
  ): Promise<FeatureRecord[]> {
    const query = resolveRegion(this.assembly, region, this.trackId);
    if (query.start === query.end) return [];
    try {
      const reader = await this.getBigBed();
      const features = await reader.getFeatures(query.refName, query.start, query.end, {
        ...(options.signal ? { signal: options.signal } : {}),
      });
      throwIfAborted(options.signal, this.trackId);
      return normalizeBigBedFeatures(features, {
        assemblyKey: this.assembly.key,
        refName: query.refName,
        featureType: this.featureType,
      });
    } catch (error) {
      // A reachable BigBed handle that cannot be decoded is a parse failure;
      // open() already reports a missing/unreadable location as "fetch".
      throw toGenomeDataError(
        error,
        "parse",
        `Failed to read interval features ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
