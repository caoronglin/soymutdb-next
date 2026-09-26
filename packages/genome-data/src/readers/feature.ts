import { TabixIndexedFile } from "@gmod/tabix";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { FeatureRecord, Region } from "../types";
import { resolveRegion, throwIfAborted, toGenomeDataError, type ReadOptions } from "./common";

export interface FeatureReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly gff: GenomeLocation;
  readonly index: GenomeLocation;
  readonly trackId?: string;
}

function decodeValue(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Parse GFF3 column 9. Percent-encoding is decoded and repeated keys keep their
 * first value, which is the convention for Parent on multi-parent features.
 */
export function parseGff3Attributes(raw: string): Record<string, string> {
  const attributes: Record<string, string> = {};
  for (const field of raw.split(";")) {
    if (!field) continue;
    const separator = field.indexOf("=");
    if (separator === -1) {
      attributes[decodeValue(field)] = "";
      continue;
    }
    const key = decodeValue(field.slice(0, separator));
    const value = decodeValue(field.slice(separator + 1));
    if (!(key in attributes)) attributes[key] = value;
  }
  return attributes;
}

function parseStrand(value: string): "+" | "-" | "." {
  return value === "+" || value === "-" ? value : ".";
}

/** Normalize one GFF3 line from a tabix query into a FeatureRecord. */
export function normalizeGff3Line(
  line: string,
  options: {
    readonly assemblyKey: string;
    readonly trackId?: string;
  },
): FeatureRecord {
  const columns = line.split("\t");
  if (columns.length < 9) {
    throw new GenomeDataError(
      "parse",
      `GFF3 line has ${String(columns.length)} columns (expected at least 9): ${line.slice(0, 120)}`,
      { trackId: options.trackId },
    );
  }
  const [seqid, , type, startText, endText, scoreText, strandText, phaseText, attrText] =
    columns;
  const start1 = Number.parseInt(startText, 10);
  const end1 = Number.parseInt(endText, 10);
  if (!Number.isInteger(start1) || !Number.isInteger(end1) || start1 < 1 || end1 < start1) {
    throw new GenomeDataError(
      "parse",
      `GFF3 line has invalid coordinates: ${line.slice(0, 120)}`,
      { trackId: options.trackId },
    );
  }
  const attributes = parseGff3Attributes(attrText);
  const score = scoreText === "." || scoreText === "" ? undefined : Number(scoreText);
  const phase = phaseText === "." || phaseText === "" ? undefined : Number.parseInt(phaseText, 10);
  const start = start1 - 1;
  const end = end1;
  const parent = attributes.Parent?.split(",")[0];
  return {
    assemblyKey: options.assemblyKey,
    refName: seqid,
    start,
    end,
    id: attributes.ID ?? `${seqid}:${type}:${String(start)}-${String(end)}`,
    type,
    name: attributes.Name ?? attributes.gene_name ?? attributes.ID,
    strand: parseStrand(strandText),
    ...(score === undefined || Number.isNaN(score) ? {} : { score }),
    ...(phase === undefined || Number.isNaN(phase) ? {} : { phase }),
    ...(parent ? { parentId: parent } : {}),
    attributes,
  };
}

/**
 * Reads bgzip-compressed, tabix-indexed GFF3 and normalizes 1-based inclusive
 * coordinates to the internal 0-based half-open convention. exon/CDS children
 * carry parentId so a renderer can rebuild the feature hierarchy.
 */
export class FeatureReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private tabix?: Promise<TabixIndexedFile>;

  constructor(private readonly options: FeatureReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
  }

  private getTabix(): Promise<TabixIndexedFile> {
    this.tabix ??= this.openTabix();
    return this.tabix;
  }

  private async openTabix(): Promise<TabixIndexedFile> {
    const { provider, gff, index } = this.options;
    try {
      const [gffHandle, indexHandle] = await Promise.all([
        provider.open(gff),
        provider.open(index),
      ]);
      return new TabixIndexedFile({
        filehandle: gffHandle,
        tbiFilehandle: indexHandle,
      });
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open GFF3 file", {
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
      const tabix = await this.getTabix();
      const records: FeatureRecord[] = [];
      await tabix.getLines(query.refName, query.start, query.end, {
        ...(options.signal ? { signal: options.signal } : {}),
        lineCallback: (line: string) => {
          records.push(
            normalizeGff3Line(line, {
              assemblyKey: this.assembly.key,
              ...(this.trackId === undefined ? {} : { trackId: this.trackId }),
            }),
          );
        },
      });
      throwIfAborted(options.signal, this.trackId);
      return records;
    } catch (error) {
      throw toGenomeDataError(
        error,
        "fetch",
        `Failed to read features ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
