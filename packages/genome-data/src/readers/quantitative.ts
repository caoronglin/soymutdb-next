import { BigWig, type Feature as BbiFeature } from "@gmod/bbi";

import type { AssemblyContext } from "../assembly";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { QuantRecord, Region } from "../types";
import { resolveRegion, toGenomeDataError, type ReadOptions } from "./common";

export interface QuantitativeReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly bigWig: GenomeLocation;
  readonly trackId?: string;
}

/** Normalize raw BigWig spans into assembly-scoped quant records. */
export function normalizeQuantFeatures(
  features: readonly BbiFeature[],
  assemblyKey: string,
  refName: string,
): QuantRecord[] {
  return features.map((feature) => ({
    assemblyKey,
    refName,
    start: feature.start,
    end: feature.end,
    score: typeof feature.score === "number" ? feature.score : 0,
  }));
}

/** Reads BigWig quantitative tracks through @gmod/bbi. */
export class QuantitativeReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private bigWig?: Promise<BigWig>;

  constructor(private readonly options: QuantitativeReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
  }

  private getBigWig(): Promise<BigWig> {
    this.bigWig ??= this.openBigWig();
    return this.bigWig;
  }

  private async openBigWig(): Promise<BigWig> {
    const { provider, bigWig } = this.options;
    try {
      const handle = await provider.open(bigWig);
      return new BigWig({ filehandle: handle });
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open BigWig file", {
        trackId: this.trackId,
      });
    }
  }

  async getQuantitative(
    region: Region,
    options: ReadOptions = {},
  ): Promise<QuantRecord[]> {
    const query = resolveRegion(this.assembly, region, this.trackId);
    if (query.start === query.end) return [];
    try {
      const reader = await this.getBigWig();
      const features = await reader.getFeatures(query.refName, query.start, query.end, {
        ...(options.signal ? { signal: options.signal } : {}),
      });
      return normalizeQuantFeatures(features, this.assembly.key, query.refName);
    } catch (error) {
      // A reachable BigWig handle that cannot be decoded is a parse failure;
      // open() already reports a missing/unreadable location as "fetch".
      throw toGenomeDataError(
        error,
        "parse",
        `Failed to read quantitative data ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
