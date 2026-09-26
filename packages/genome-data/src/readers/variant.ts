import { TabixIndexedFile } from "@gmod/tabix";
import VCF from "@gmod/vcf";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import type { Region, VariantRecord } from "../types";
import {
  OpenCache,
  resolveRegion,
  throwIfAborted,
  toGenomeDataError,
  type ReadOptions,
} from "./common";

export type VariantKind = VariantRecord["kind"];

export interface VariantReaderOptions {
  readonly provider: FileProvider;
  readonly assembly: AssemblyContext;
  readonly vcf: GenomeLocation;
  readonly index: GenomeLocation;
  readonly trackId?: string;
}

/** The subset of @gmod/vcf's untyped parseLine() result this reader consumes. */
interface ParsedVcfLine {
  readonly CHROM: string;
  readonly POS: number;
  readonly ID: readonly string[] | null;
  readonly REF: string;
  readonly ALT: readonly string[] | null;
  readonly QUAL: number | null;
  readonly INFO?: Record<string, unknown> | null;
}

const SYMBOLIC_ALLELE = /^<[^>]+>$/;

/** True for VCF breakend notation (e.g. "N[chr2:321682["). */
export function isBreakendAllele(allele: string): boolean {
  return allele.includes("[") || allele.includes("]");
}

/** True for symbolic structural alleles (e.g. "<DEL>", "<DUP>"). */
export function isSymbolicAllele(allele: string): boolean {
  return SYMBOLIC_ALLELE.test(allele);
}

/**
 * Classify a single REF/ALT pair using length comparison after symbolic and
 * breakend alleles have been recognised as structural variants.
 */
export function classifyAllele(ref: string, alt: string): VariantKind {
  if (!ref || !alt || alt === "." || alt === "*") return "other";
  if (isSymbolicAllele(alt) || isBreakendAllele(alt)) return "sv";
  if (ref.length === alt.length) return ref.length === 1 ? "snv" : "mnv";
  return alt.length > ref.length ? "ins" : "del";
}

/**
 * Classify a whole record. Any structural allele makes the record structural;
 * otherwise all alleles must agree, and a mixed record falls back to "other".
 */
export function classifyVariantKind(
  ref: string,
  alts: readonly string[],
): VariantKind {
  const kinds = alts
    .filter((alt) => alt !== "" && alt !== ".")
    .map((alt) => classifyAllele(ref, alt));
  if (kinds.length === 0) return "other";
  if (kinds.includes("sv")) return "sv";
  const unique = new Set(kinds);
  return unique.size === 1 ? kinds[0] : "other";
}

function toInteger(value: unknown): number | undefined {
  // @gmod/vcf stores every INFO value as an array (even Number=1 fields).
  if (Array.isArray(value)) return value.length > 0 ? toInteger(value[0]) : undefined;
  if (typeof value === "number") return Number.isInteger(value) ? value : undefined;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isInteger(parsed) ? parsed : undefined;
  }
  return undefined;
}

/**
 * 0-based half-open end for a VCF record. VCF POS is 1-based inclusive; the
 * reference length covers simple alleles and INFO/END (which is itself 1-based
 * inclusive) covers symbolic and large events.
 */
export function variantEnd(
  start: number,
  ref: string,
  info?: Record<string, unknown> | null,
): number {
  const byRef = start + Math.max(ref.length, 1);
  const byInfo = toInteger(info?.END);
  if (byInfo !== undefined && byInfo > byRef) return byInfo;
  return byRef;
}

/** Normalize a raw VCF data line into an assembly-scoped VariantRecord. */
export function normalizeVariantLine(
  line: string,
  options: {
    readonly parser: VCF;
    readonly assemblyKey: string;
    readonly trackId?: string;
  },
): VariantRecord {
  let parsed: ParsedVcfLine | undefined;
  try {
    parsed = options.parser.parseLine(line) as ParsedVcfLine | undefined;
  } catch (error) {
    throw new GenomeDataError("parse", `Malformed VCF line: ${line.slice(0, 120)}`, {
      trackId: options.trackId,
      cause: error,
    });
  }
  if (!parsed || typeof parsed.CHROM !== "string") {
    throw new GenomeDataError("parse", `Malformed VCF line: ${line.slice(0, 120)}`, {
      trackId: options.trackId,
    });
  }
  if (!Number.isInteger(parsed.POS) || parsed.POS < 1) {
    throw new GenomeDataError(
      "parse",
      `VCF line "${line.slice(0, 120)}" has an invalid POS: ${String(parsed.POS)}`,
      { trackId: options.trackId },
    );
  }
  const ref = parsed.REF ?? "";
  const alt = (parsed.ALT ?? []).filter((allele) => allele !== ".");
  const start = parsed.POS - 1;
  const firstId = parsed.ID?.[0];
  const id =
    firstId && firstId !== "."
      ? firstId
      : `${parsed.CHROM}:${String(start)}-${String(variantEnd(start, ref, parsed.INFO))}:${ref}>${alt.join(",")}`;
  return {
    assemblyKey: options.assemblyKey,
    refName: parsed.CHROM,
    start,
    end: variantEnd(start, ref, parsed.INFO),
    id,
    ref,
    alt,
    kind: classifyVariantKind(ref, alt),
    quality: parsed.QUAL === null ? undefined : parsed.QUAL,
    info: parsed.INFO ?? {},
  };
}

/**
 * Reads bgzip-compressed, tabix-indexed VCF. POS is converted from 1-based
 * inclusive to the internal 0-based half-open convention.
 */
export class VariantReader {
  private readonly assembly: AssemblyContext;
  private readonly trackId?: string;
  private readonly tabixCache = new OpenCache<TabixIndexedFile>();
  private readonly parserCache = new OpenCache<VCF>();

  constructor(private readonly options: VariantReaderOptions) {
    this.assembly = options.assembly;
    this.trackId = options.trackId;
  }

  private getTabix(): Promise<TabixIndexedFile> {
    return this.tabixCache.run(() => this.openTabix());
  }

  private async openTabix(): Promise<TabixIndexedFile> {
    const { provider, vcf, index } = this.options;
    try {
      const [vcfHandle, indexHandle] = await Promise.all([
        provider.open(vcf),
        provider.open(index),
      ]);
      return new TabixIndexedFile({
        filehandle: vcfHandle,
        tbiFilehandle: indexHandle,
      });
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open VCF file", {
        trackId: this.trackId,
      });
    }
  }

  private getParser(): Promise<VCF> {
    return this.parserCache.run(() => this.createParser());
  }

  private async createParser(): Promise<VCF> {
    const tabix = await this.getTabix();
    let header: string;
    try {
      header = await tabix.getHeader();
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to read VCF header", {
        trackId: this.trackId,
      });
    }
    try {
      return new VCF({ header });
    } catch (error) {
      throw new GenomeDataError("parse", "Invalid VCF header", {
        trackId: this.trackId,
        cause: error,
      });
    }
  }

  async getVariants(
    region: Region,
    options: ReadOptions = {},
  ): Promise<VariantRecord[]> {
    const query = resolveRegion(this.assembly, region, this.trackId);
    if (query.start === query.end) return [];
    try {
      const [tabix, parser] = await Promise.all([this.getTabix(), this.getParser()]);
      const records: VariantRecord[] = [];
      await tabix.getLines(query.refName, query.start, query.end, {
        ...(options.signal ? { signal: options.signal } : {}),
        lineCallback: (line: string) => {
          records.push(
            normalizeVariantLine(line, {
              parser,
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
        `Failed to read variants ${query.refName}:${String(query.start)}-${String(query.end)}`,
        { trackId: this.trackId },
      );
    }
  }
}
