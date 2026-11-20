/**
 * Typed client for `/tools/sequence/*` — the Rust bio-core endpoints.
 *
 * These are public utilities (`auth: false`). They operate only on sequence
 * text the caller supplies; no assembly, release or genome record is read, so
 * no genomic coordinate or genome-browser link is ever produced here. That is
 * deliberately *not* BLAST — full searches stay on `/blast`.
 *
 * Two things worth knowing before using these:
 *
 * 1. **Defaults are caller-optional.** `openapi-typescript` reads a schema
 *    `default` as "always present in the response", which makes the field
 *    required on *requests* too. For a request that is backwards: the server
 *    fills the default. The `*Request` aliases below drop exactly the fields
 *    the API defaults and nothing else.
 * 2. **Kernel codes are not API codes.** The error envelope carries
 *    `error.code = "validation_error"` at the API level; the kernel's own
 *    machine code (e.g. `UNKNOWN_GENETIC_CODE`) rides in
 *    `error.details.code`. `sequenceKernelCode` reads the latter, because
 *    "validation_error" never tells a caller which input to fix.
 */

import type { components } from "./generated/openapi";
import { ApiError, request, TimeoutPresets } from "./client";

type Schemas = components["schemas"];

/** Engine identity. Distinct from a biological data release. */
export type EngineMetadata = Schemas["EngineMetadata"];
export type Alphabet = NonNullable<Schemas["ReverseComplementRequest"]["alphabet"]>;

/**
 * Supported operations, formats and limits — plus whether the compiled kernel
 * is present at all. `available: false` is a real state (wheel not installed),
 * not an error: the page must be able to say "not deployed" instead of
 * surfacing a 503 for every click.
 */
export type SequenceCapabilities = Schemas["SequenceCapabilitiesResponse"];

export type ReverseComplementRequest = Schemas["ReverseComplementRequest"];
export type ReverseComplementResponse = Schemas["ReverseComplementResponse"];

export type MatchHit = Schemas["MatchHit"];
export type MatchMode = NonNullable<Schemas["SequenceMatchRequest"]["mode"]>;
export type SequenceMatchResponse = Schemas["SequenceMatchResponse"];

export type SequenceAlignResponse = Schemas["SequenceAlignResponse"];
export type AlignmentMode = NonNullable<Schemas["SequenceAlignRequest"]["mode"]>;

export type SequenceStatsResponse = Schemas["SequenceStatsResponse"];

export type OrfCandidate = Schemas["OrfCandidate"];
export type OrfResponse = Schemas["OrfResponse"];

export type TranslateResponse = Schemas["TranslateResponse"];

export type KmerItem = Schemas["KmerItem"];
export type KmerResponse = Schemas["KmerResponse"];

export type FormatInspectResponse = Schemas["FormatInspectResponse"];
export type SequenceFormat = NonNullable<Schemas["FormatInspectRequest"]["fmt"]>;

export type ConvertFormatResponse = Schemas["ConvertFormatResponse"];
export type SequenceTextFormat = NonNullable<Schemas["ConvertFormatRequest"]["source_format"]>;

export type RestrictionEnzymeResult = Schemas["RestrictionEnzymeResult"];
export type RestrictionResponse = Schemas["RestrictionResponse"];

export type ProteinPropertiesResponse = Schemas["ProteinPropertiesResponse"];

export type MeltingTempResponse = Schemas["MeltingTempResponse"];
export type MeltingTempMethod = NonNullable<Schemas["MeltingTempRequest"]["method"]>;

export type MultipleAlignmentResponse = Schemas["MultipleAlignmentResponse"];

export type TreeResponse = Schemas["TreeResponse"];

/** Match target is a discriminated inline sequence — no path, key or URL. */
export interface InlineTargetInput {
  kind: "inline";
  sequence: string;
}

export interface MatchRequestInput {
  pattern: string;
  target: InlineTargetInput;
  alphabet?: Alphabet;
  mode?: MatchMode;
  both_strands?: boolean;
  max_edits?: number;
  max_hits?: number;
}

export interface AlignRequestInput {
  query: string;
  target: string;
  alphabet?: Alphabet;
  mode?: AlignmentMode;
  scoring?: Schemas["ScoringConfig"];
}

export interface ConvertFormatInput {
  data: string;
  source_format?: SequenceTextFormat;
  target_format?: SequenceTextFormat;
  max_records?: number;
}

export interface RestrictionSitesInput {
  sequence: string;
  /** Empty scans every known enzyme and reports the ones with a site. */
  enzymes?: string[];
  circular?: boolean;
  max_hits?: number;
}

export interface ProteinPropertiesInput {
  protein: string;
}

export interface MeltingTempInput {
  sequence: string;
  method?: MeltingTempMethod;
  dna_conc_nm?: number;
  salt_conc_mm?: number;
}

export interface MultipleAlignmentInput {
  sequences: string[];
  alphabet?: Alphabet;
  mode?: AlignmentMode;
}

export interface TreeInput {
  sequences: string[];
  labels?: string[];
  alphabet?: Alphabet;
}

export interface ReverseComplementInput {
  sequence: string;
  alphabet?: Alphabet;
  preserve_case?: boolean;
}

export interface StatsInput {
  sequence: string;
  alphabet?: Alphabet;
  ambiguous_gc_policy?: "exclude" | "include";
}

export interface OrfInput {
  sequence: string;
  min_len?: number;
  limit?: number;
}

export interface TranslateInput {
  sequence: string;
  genetic_code_id?: number;
  frame?: number;
}

export interface KmerInput {
  sequence: string;
  k?: number;
  canonical?: boolean;
  ambiguity_policy?: "skip" | "reject";
  max_items?: number;
}

/**
 * Kernel codes the API surfaces through `error.details.code`.
 *
 * Kept as a plain list (not a `Record`) so an unrecognised code falls through
 * to the generic message rather than being silently mapped to a wrong one.
 */
export const SEQUENCE_KERNEL_CODES = [
  "EMPTY_SEQUENCE",
  "INVALID_CHARACTER",
  "UNSUPPORTED_ALPHABET",
  "SEQUENCE_TOO_LONG",
  "BUDGET_EXCEEDED",
  "INVALID_INTERVAL",
  "COORDINATE_OVERFLOW",
  "UNSUPPORTED_PARAMETER",
  "UNKNOWN_GENETIC_CODE",
  "INVALID_RECORD",
] as const;

export type SequenceKernelCode = (typeof SEQUENCE_KERNEL_CODES)[number];

function isKernelCode(value: unknown): value is SequenceKernelCode {
  return typeof value === "string" && (SEQUENCE_KERNEL_CODES as readonly string[]).includes(value);
}

/**
 * Read the kernel's own machine code off an API failure.
 *
 * Returns `null` when the failure is not one the kernel produced — a 503 from
 * an absent wheel, a 429, a network error. Callers must distinguish that from
 * "the kernel rejected this input", because only the latter is fixable by the
 * user editing the sequence.
 */
export function sequenceKernelCode(err: unknown): SequenceKernelCode | null {
  if (!(err instanceof ApiError)) return null;
  const envelope = err.details;
  if (envelope === null || typeof envelope !== "object") return null;
  const error = (envelope as Record<string, unknown>).error;
  if (error === null || typeof error !== "object") return null;
  const details = (error as Record<string, unknown>).details;
  if (details === null || typeof details !== "object") return null;
  const code = (details as Record<string, unknown>).code;
  return isKernelCode(code) ? code : null;
}

/** True when the compiled kernel is missing server-side (503, not a rejection). */
export function isKernelUnavailable(err: unknown): boolean {
  return err instanceof ApiError && err.status === 503;
}

/**
 * Count sequence characters the way the kernel budget does.
 *
 * Whitespace and FASTA header lines are not sequence, so they must not push a
 * paste over the kernel's inline limit — a 1 MiB FASTA file and a 1 MiB raw
 * string are not the same request.
 */
export function countSequenceCharacters(text: string): number {
  let count = 0;
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith(">") || trimmed === "") continue;
    count += trimmed.length;
  }
  return count;
}

const BASE = "/tools/sequence";

/** Public utility: no Bearer header, generous timeout for CPU-bound work. */
function post<T>(path: string, json: unknown): Promise<T> {
  return request<T>(`${BASE}${path}`, {
    method: "POST",
    json,
    auth: false,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

export const sequenceApi = {
  /** Always answers, even when the kernel is missing. */
  capabilities(): Promise<SequenceCapabilities> {
    return request<SequenceCapabilities>(`${BASE}/capabilities`, {
      auth: false,
      timeoutMs: TimeoutPresets.NON_CRITICAL,
    });
  },

  reverseComplement(input: ReverseComplementInput): Promise<ReverseComplementResponse> {
    return post<ReverseComplementResponse>("/reverse-complement", input);
  },

  match(input: MatchRequestInput): Promise<SequenceMatchResponse> {
    return post<SequenceMatchResponse>("/match", input);
  },

  align(input: AlignRequestInput): Promise<SequenceAlignResponse> {
    return post<SequenceAlignResponse>("/align", input);
  },

  stats(input: StatsInput): Promise<SequenceStatsResponse> {
    return post<SequenceStatsResponse>("/stats", input);
  },

  orfs(input: OrfInput): Promise<OrfResponse> {
    return post<OrfResponse>("/orfs", input);
  },

  translate(input: TranslateInput): Promise<TranslateResponse> {
    return post<TranslateResponse>("/translate", input);
  },

  kmers(input: KmerInput): Promise<KmerResponse> {
    return post<KmerResponse>("/kmers", input);
  },

  /** Validate a FASTA/FASTQ/BED payload. `data` is base64, never a path. */
  inspect(fmt: SequenceFormat, base64Data: string): Promise<FormatInspectResponse> {
    return post<FormatInspectResponse>("/inspect", { fmt, data: base64Data });
  },

  /** Convert records between FASTA / GenBank / EMBL / tabular text. */
  convertFormat(input: ConvertFormatInput): Promise<ConvertFormatResponse> {
    return post<ConvertFormatResponse>("/convert", input);
  },

  /** Cut sites of one or more restriction enzymes (REBASE). */
  restrictionSites(input: RestrictionSitesInput): Promise<RestrictionResponse> {
    return post<RestrictionResponse>("/restriction-sites", input);
  },

  /** Molecular weight, isoelectric point, extinction and hydrophobicity. */
  proteinProperties(input: ProteinPropertiesInput): Promise<ProteinPropertiesResponse> {
    return post<ProteinPropertiesResponse>("/protein-properties", input);
  },

  /** Primer melting temperature: Wallace, GC or nearest-neighbour. */
  meltingTemp(input: MeltingTempInput): Promise<MeltingTempResponse> {
    return post<MeltingTempResponse>("/melting-temp", input);
  },

  /** Progressively align several sequences and score the result. */
  multipleAlignment(input: MultipleAlignmentInput): Promise<MultipleAlignmentResponse> {
    return post<MultipleAlignmentResponse>("/multiple-alignment", input);
  },

  /** Neighbour-joining tree over the sequences, as Newick text. */
  tree(input: TreeInput): Promise<TreeResponse> {
    return post<TreeResponse>("/tree", input);
  },
};
