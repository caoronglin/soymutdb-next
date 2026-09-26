import { BamFile, type BamRecord } from "@gmod/bam";

import type { AssemblyContext } from "../assembly";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { AlignmentRecord, Region } from "../types";
import {
  OpenCache,
  resolveRegion,
  throwIfAborted,
  toGenomeDataError,
  type ReadOptions,
} from "./common";

/** SAM flag bit 0x10 marks a read mapped to the reverse strand. */
const BAM_REVERSE_FLAG = 0x10;

export interface AlignmentReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly bam: GenomeLocation;
  readonly index: GenomeLocation;
  readonly trackId?: string;
}

/**
 * Normalize @gmod/bam records into assembly-scoped alignments.
 *
 * BamRecord.start/end are already 0-based half-open (the BAM contract), so no
 * coordinate conversion is needed here; strand is derived from the flags word
 * rather than the library's convenience getter so the mapping stays explicit.
 */
export function normalizeBamRecords(
  records: readonly BamRecord[],
  options: { readonly assemblyKey: string; readonly refName: string },
): AlignmentRecord[] {
  return records.map((record) => {
    const flags = record.flags;
    const readName = record.name;
    const start = record.start;
    const end = record.end;
    return {
      assemblyKey: options.assemblyKey,
      refName: options.refName,
      start,
      end,
      id: readName + ":" + options.refName + ":" + String(start) + "-" + String(end),
      readName,
      read: record.seq,
      strand: (flags & BAM_REVERSE_FLAG) === 0 ? "+" : "-",
      cigar: record.CIGAR,
      ...(record.mq === undefined ? {} : { mapq: record.mq }),
      templateLength: record.template_length,
      flags,
    };
  });
}

/**
 * Reads BAM alignments through @gmod/bam.
 *
 * The BAM header and BAI index are resolved on first read so constructing a
 * reader from the track factory never performs I/O. A missing or unreadable
 * file/index is reported as "fetch"; a failure while decoding an already open
 * BAM is reported as "parse".
 */
export class AlignmentReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private readonly bamCache = new OpenCache<BamFile>();

  constructor(private readonly options: AlignmentReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
  }

  private getBam(): Promise<BamFile> {
    return this.bamCache.run(() => this.openBam());
  }

  private async openBam(): Promise<BamFile> {
    const { provider, bam, index } = this.options;
    try {
      const [bamHandle, indexHandle] = await Promise.all([
        provider.open(bam),
        provider.open(index),
      ]);
      const file = new BamFile({ bamFilehandle: bamHandle, baiFilehandle: indexHandle });
      // @gmod/bam requires the header to be parsed before any range query.
      await file.getHeader();
      return file;
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open BAM file", {
        trackId: this.trackId,
      });
    }
  }

  async getAlignments(
    region: Region,
    options: ReadOptions = {},
  ): Promise<AlignmentRecord[]> {
    const query = resolveRegion(this.assembly, region, this.trackId);
    if (query.start === query.end) return [];
    try {
      const reader = await this.getBam();
      const records = await reader.getRecordsForRange(
        query.refName,
        query.start,
        query.end,
        { ...(options.signal ? { signal: options.signal } : {}) },
      );
      throwIfAborted(options.signal, this.trackId);
      return normalizeBamRecords(records, {
        assemblyKey: this.assembly.key,
        refName: query.refName,
      });
    } catch (error) {
      throw toGenomeDataError(
        error,
        "parse",
        `Failed to read alignments ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
