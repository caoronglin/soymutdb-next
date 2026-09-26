import Trix from "@gmod/trix";

import type { FileProvider } from "../file-provider";
import type { GenomeLocation } from "../location";
import { OpenCache, toGenomeDataError } from "./common";

export interface TextSearchReaderOptions {
  readonly provider: FileProvider;
  /** The .ixx prefix index location. */
  readonly ixx: GenomeLocation;
  /** The .ix term index location. */
  readonly ix: GenomeLocation;
  readonly trackId?: string;
  /** Internal fetch cap passed to @gmod/trix (default 1500). */
  readonly maxResults?: number;
}

/** A normalized Trix hit: the matched term plus its opaque record payload. */
export interface TextSearchResult {
  /** The matched index term (trix's first tuple element). */
  readonly id: string;
  /** The opaque record payload (trix's second tuple element). */
  readonly label: string;
}

const DEFAULT_MAX_RESULTS = 1500;

/**
 * Prefix search over a Trix text index.
 *
 * @gmod/trix returns [term, payload] pairs where the payload encodes the
 * location, track and display fields with "|" substituted for commas. This
 * reader keeps that raw payload as `label`; decoding it belongs to the track
 * that owns the index, not to the format reader.
 */
export class TextSearchReader {
  private readonly trackId?: string;
  private readonly limitCap: number;
  private readonly trixCache = new OpenCache<Trix>();

  constructor(private readonly options: TextSearchReaderOptions) {
    this.trackId = options.trackId;
    this.limitCap = options.maxResults ?? DEFAULT_MAX_RESULTS;
  }

  private getTrix(): Promise<Trix> {
    return this.trixCache.run(() => this.openTrix());
  }

  private async openTrix(): Promise<Trix> {
    const { provider, ixx, ix } = this.options;
    try {
      const [ixxHandle, ixHandle] = await Promise.all([
        provider.open(ixx),
        provider.open(ix),
      ]);
      return new Trix(ixxHandle, ixHandle, this.limitCap);
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Failed to open Trix index", {
        trackId: this.trackId,
      });
    }
  }

  async search(
    prefix: string,
    limit = 20,
    options: { readonly signal?: AbortSignal } = {},
  ): Promise<TextSearchResult[]> {
    const query = prefix.trim();
    if (!query || limit <= 0) return [];
    try {
      const trix = await this.getTrix();
      const hits = await trix.search(query, {
        ...(options.signal ? { signal: options.signal } : {}),
      });
      return hits
        .slice(0, Math.min(limit, this.limitCap))
        .map(([term, payload]) => ({ id: term, label: payload }));
    } catch (error) {
      throw toGenomeDataError(error, "fetch", "Trix search failed for " + query, {
        trackId: this.trackId,
      });
    }
  }
}
