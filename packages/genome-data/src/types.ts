/**
 * Normalized, assembly-scoped genome records.
 *
 * All intervals are 0-based half-open internally; the 1-based inclusive
 * boundary used by deep links is produced only at the UI/bridge edge.
 */
export interface Region {
  /** Stable assembly key; v4 and v5 are distinct namespaces. */
  readonly assemblyKey: string;
  readonly refName: string;
  /** 0-based inclusive start. */
  readonly start: number;
  /** 0-based exclusive end. */
  readonly end: number;
}

export interface FeatureRecord extends Region {
  readonly id: string;
  readonly type: string;
  readonly name?: string;
  readonly strand?: "+" | "-" | ".";
  readonly score?: number;
  readonly phase?: number;
  readonly parentId?: string;
  readonly attributes?: Readonly<Record<string, string>>;
}

export interface VariantRecord extends Region {
  readonly id: string;
  readonly ref: string;
  readonly alt: readonly string[];
  readonly kind: "snv" | "mnv" | "ins" | "del" | "sv" | "other";
  readonly quality?: number;
  readonly info?: Readonly<Record<string, unknown>>;
}

export interface QuantRecord extends Region {
  /** Optional stable id; consumers synthesize one from the interval when absent. */
  readonly id?: string;
  readonly score: number;
}

export interface SequenceChunk {
  readonly assemblyKey: string;
  readonly refName: string;
  readonly start: number;
  readonly bases: string;
}

export interface AlignmentRecord extends Region {
  readonly id: string;
  readonly readName: string;
  readonly read: string;
  readonly strand: "+" | "-";
  readonly cigar?: string;
  readonly mapq?: number;
  readonly templateLength?: number;
  readonly flags?: number;
}

/** A backend track definition (a superset of the JBrowse config shape). */
export interface TrackConfig {
  readonly trackId: string;
  readonly name: string;
  readonly type: string;
  readonly assemblyNames: readonly string[];
  readonly category?: readonly string[];
  readonly description?: string;
  readonly adapter?: Readonly<Record<string, unknown>>;
  readonly [key: string]: unknown;
}
