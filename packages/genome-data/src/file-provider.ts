import { RemoteFile, type GenericFilehandle } from "generic-filehandle";

import { BufferFilehandle } from "./buffer-filehandle";
import { LruCache } from "./cache";
import { GenomeDataError } from "./errors";
import { locationKey, type GenomeLocation } from "./location";

/** Opens a genome data location as a random-access file handle. */
export interface FileProvider {
  open(location: GenomeLocation): Promise<GenericFilehandle>;
}

/** Production provider: HTTP(S) range requests via generic-filehandle. */
export class UriFileProvider implements FileProvider {
  async open(location: GenomeLocation): Promise<GenericFilehandle> {
    if (location.kind !== "uri") {
      throw new GenomeDataError(
        "unsupported-type",
        "UriFileProvider cannot open a " + location.kind + " location",
      );
    }
    return new RemoteFile(location.uri);
  }
}

/**
 * Test provider backed by in-memory bytes. Fixtures are registered under the
 * same location the reader would fetch, so tests never touch the network.
 */
export class MemoryFileProvider implements FileProvider {
  private readonly files = new Map<string, Uint8Array>();

  add(location: GenomeLocation, data: Uint8Array | string): void {
    const bytes = typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);
    this.files.set(locationKey(location), bytes);
  }

  has(location: GenomeLocation): boolean {
    return this.files.has(locationKey(location));
  }

  async open(location: GenomeLocation): Promise<GenericFilehandle> {
    const bytes = this.files.get(locationKey(location));
    if (!bytes) {
      throw new GenomeDataError("fetch", "No in-memory file for " + locationKey(location));
    }
    // See BufferFilehandle: the framework's readFile overload is not satisfiable.
    return new BufferFilehandle(bytes, locationKey(location)) as unknown as GenericFilehandle;
  }
}

/** Reuses open handles per location and closes handles evicted by the LRU. */
export class CachingFileProvider implements FileProvider {
  private readonly cache: LruCache<string, GenericFilehandle>;

  constructor(
    private readonly inner: FileProvider,
    capacity = 32,
  ) {
    this.cache = new LruCache(capacity);
  }

  async open(location: GenomeLocation): Promise<GenericFilehandle> {
    const key = locationKey(location);
    const cached = this.cache.get(key);
    if (cached) return cached;
    const handle = await this.inner.open(location);
    const evicted = this.cache.set(key, handle);
    if (evicted && evicted !== handle) {
      void Promise.resolve(evicted.close?.()).catch(() => undefined);
    }
    return handle;
  }
}
