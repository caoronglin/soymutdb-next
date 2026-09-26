import { BgzipIndexedFasta } from "@gmod/indexedfasta";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { Region, SequenceChunk } from "../types";
import {
  resolveRegion,
  toGenomeDataError,
  type ReadOptions,
  throwIfAborted,
} from "./common";

/** A reference sequence span with its assembly-scoped size. */
export interface ChromSize {
  readonly refName: string;
  readonly size: number;
}

export interface SequenceReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly fasta: GenomeLocation;
  readonly fai: GenomeLocation;
  readonly gzi: GenomeLocation;
  readonly trackId?: string;
  /** Maximum uncompressed bytes fetched for a single read (default 1 MiB). */
  readonly chunkSizeLimit?: number;
}

/**
 * Reads bgzip-compressed FASTA through its .fai/.gzi indexes.
 *
 * Handles are resolved lazily on the first read so constructing a reader (e.g.
 * from the track factory) never performs I/O, and every failure is routed
 * through the GenomeDataError surface.
 */
export class SequenceReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private ready?: Promise<BgzipIndexedFasta>;

  constructor(private readonly options: SequenceReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
  }

  private getReady(): Promise<BgzipIndexedFasta> {
    this.ready ??= this.open(this.options);
    return this.ready;
  }

  private async open(options: SequenceReaderOptions): Promise<BgzipIndexedFasta> {
    const { provider, fasta, fai, gzi } = options;
    try {
      const [fastaHandle, faiHandle, gziHandle] = await Promise.all([
        provider.open(fasta),
        provider.open(fai),
        provider.open(gzi),
      ]);
      return new BgzipIndexedFasta({
        fasta: fastaHandle,
        fai: faiHandle,
        gzi: gziHandle,
        ...(options.chunkSizeLimit === undefined
          ? {}
          : { chunkSizeLimit: options.chunkSizeLimit }),
      });
    } catch (error) {
      throw toGenomeDataError(
        error,
        "fetch",
        "Failed to open reference sequence files",
        { trackId: this.trackId },
      );
    }
  }

  /** Reference names declared by the FASTA index, in file order. */
  async getSequenceNames(options: ReadOptions = {}): Promise<string[]> {
    try {
      return await (await this.getReady()).getSequenceNames(options);
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to read FASTA index", {
        trackId: this.trackId,
      });
    }
  }

  /** Reference name and length pairs, the reference half of chrom.sizes. */
  async getChromSizes(options: ReadOptions = {}): Promise<ChromSize[]> {
    try {
      const sizes = await (await this.getReady()).getSequenceSizes(options);
      return Object.entries(sizes).map(([refName, size]) => ({ refName, size }));
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to read chrom sizes", {
        trackId: this.trackId,
      });
    }
  }

  /**
   * Sequence for a 0-based half-open region. Out-of-range coordinates are
   * clamped by the underlying index; an empty region yields "".
   */
  async getSequence(
    region: Region,
    options: ReadOptions = {},
  ): Promise<SequenceChunk> {
    const query = resolveRegion(this.assembly, region, this.trackId);
    if (query.start === query.end) {
      return {
        assemblyKey: this.assembly.key,
        refName: query.refName,
        start: query.start,
        bases: "",
      };
    }
    try {
      const bases = await (
        await this.getReady()
      ).getSequence(query.refName, query.start, query.end, options);
      throwIfAborted(options.signal, this.trackId);
      if (bases === undefined) {
        throw new GenomeDataError(
          "assembly-mismatch",
          `Reference "${query.refName}" is not present in the FASTA index of assembly "${this.assembly.key}"`,
          { trackId: this.trackId },
        );
      }
      return {
        assemblyKey: this.assembly.key,
        refName: query.refName,
        start: query.start,
        bases,
      };
    } catch (error) {
      throw toGenomeDataError(
        error,
        "fetch",
        `Failed to read sequence ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
