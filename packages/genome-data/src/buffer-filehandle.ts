import { Buffer } from "buffer";

import type { FilehandleOptions, Stats } from "generic-filehandle";

/**
 * In-memory random-access handle.
 *
 * generic-filehandle ships BlobFile, but BlobFile reads through the browser
 * FileReader API and therefore cannot run under Node (vitest, SSR, workers).
 * This handle serves the same runtime contract from a byte array so tests and
 * non-browser consumers never need a DOM.
 *
 * It intentionally does not declare `implements GenericFilehandle`: that
 * interface's readFile conditional overload is invertible and not satisfiable
 * by any correct implementation, so providers cast once at the boundary.
 */
export class BufferFilehandle {
  constructor(
    private readonly data: Uint8Array,
    private readonly name = "memory",
  ) {}

  async read(
    buf: Buffer,
    offset: number,
    length: number,
    position: number,
  ): Promise<{ bytesRead: number; buffer: Buffer }> {
    const start = Math.max(0, position);
    const end = Math.min(start + length, this.data.length);
    const slice = this.data.subarray(start, end);
    Buffer.from(slice).copy(buf, offset);
    return { bytesRead: slice.length, buffer: buf };
  }

  async readFile(options?: FilehandleOptions | BufferEncoding): Promise<Buffer | string> {
    const encoding = typeof options === "string" ? options : options?.encoding;
    const buffer = Buffer.from(this.data);
    return encoding ? buffer.toString(encoding) : buffer;
  }

  async stat(): Promise<Stats> {
    return { size: this.data.length, name: this.name };
  }

  async close(): Promise<void> {
    // In-memory: nothing to release.
  }
}
