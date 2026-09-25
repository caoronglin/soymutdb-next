import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { IncrementalSha256 } from "./incremental-sha256";

function expectedSha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

describe("IncrementalSha256", () => {
  it("matches canonical SHA-256 across padding and fragmented-update boundaries", () => {
    for (const length of [0, 1, 55, 56, 63, 64, 65, 4_194_307, 4_194_304, 4_194_305]) {
      const bytes = new Uint8Array(length);
      for (let index = 0; index < bytes.length; index += 1) bytes[index] = index % 251;

      const hasher = new IncrementalSha256();
      for (let offset = 0; offset < bytes.length; offset += 17) {
        hasher.update(bytes.subarray(offset, offset + 17));
      }

      expect(hasher.digestHex()).toBe(expectedSha256(bytes));
    }
  });

  it("does not permit updates or repeated digests after finalization", () => {
    const hasher = new IncrementalSha256();
    hasher.update(new TextEncoder().encode("abc"));
    hasher.digestHex();

    expect(() => hasher.update(new Uint8Array([1]))).toThrow(/finalized/i);
    expect(() => hasher.digestHex()).toThrow(/finalized/i);
  });
});
