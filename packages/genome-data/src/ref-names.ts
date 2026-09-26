import type { AssemblyContext } from "./assembly";
import type { FileProvider } from "./file-provider";
import type { GenomeLocation } from "./location";
import type { ReadOptions } from "./readers/common";
import { SequenceReader } from "./readers/sequence";

export interface AssemblyRefNameLoaderOptions {
  readonly provider: FileProvider;
  /** Assembly the indexed FASTA belongs to (used as the reader's context). */
  readonly assembly: AssemblyContext;
  readonly fasta: GenomeLocation;
  readonly fai: GenomeLocation;
  readonly gzi: GenomeLocation;
  readonly trackId?: string;
}

/**
 * Loads an assembly's complete canonical reference-name list from its bgzip
 * FASTA index exactly once, then degrades gracefully.
 *
 * The FAI is the authoritative chromosome list for an indexed FASTA, so a
 * successful load replaces any viewport-only refName the host started with and
 * makes every chromosome addressable by `resolveRefName`. A failed load is
 * swallowed: {@link load} returns the caller's fallback so rendering never
 * breaks, and a later call retries because nothing is cached.
 */
export class AssemblyRefNameLoader {
  private names: readonly string[] | null = null;
  private pending: Promise<readonly string[]> | null = null;

  constructor(private readonly options: AssemblyRefNameLoaderOptions) {}

  /** True once a non-empty name list has been loaded and cached. */
  get isLoaded(): boolean {
    return this.names !== null;
  }

  /**
   * The cached name list, or null when no successful load has happened yet.
   * Lets a host render immediately without awaiting a repeat of the same I/O.
   */
  get cached(): readonly string[] | null {
    return this.names;
  }

  /**
   * Resolve the assembly's full reference-name list.
   *
   * Returns the cached list when available; otherwise reads the FASTA index.
   * On any failure (or an empty index) it resolves to `fallback` instead of
   * rejecting, so a broken index can never break the surrounding view.
   */
  async load(
    fallback: readonly string[] = [],
    options: ReadOptions = {},
  ): Promise<readonly string[]> {
    if (this.names) return this.names;
    this.pending ??= this.readNames(options);
    try {
      const names = await this.pending;
      if (names.length > 0) {
        this.names = names;
        return names;
      }
    } catch {
      // Failure-tolerant by design: fall through to the fallback below.
    }
    // Clear the rejected/empty promise so a later mount can retry the index.
    this.pending = null;
    return fallback;
  }

  private async readNames(options: ReadOptions): Promise<readonly string[]> {
    // A fresh reader per attempt: SequenceReader memoizes its first-open
    // promise, so a rejected open must not poison a later retry.
    const reader = new SequenceReader({
      provider: this.options.provider,
      assembly: this.options.assembly,
      ...(this.options.trackId === undefined ? {} : { trackId: this.options.trackId }),
      fasta: this.options.fasta,
      fai: this.options.fai,
      gzi: this.options.gzi,
    });
    const sizes = await reader.getChromSizes(options);
    return sizes.map((size) => size.refName);
  }
}
