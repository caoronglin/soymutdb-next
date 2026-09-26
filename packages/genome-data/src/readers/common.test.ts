import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import { OpenCache, resolveRegion, toGenomeDataError } from "./common";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
  refNameAliases: { "1": "chr01" },
};

describe("toGenomeDataError", () => {
  it("wraps a plain error with the fallback code and cause", () => {
    const cause = new Error("boom");
    const wrapped = toGenomeDataError(cause, "fetch", "read failed", { trackId: "t1" });
    expect(wrapped).toBeInstanceOf(GenomeDataError);
    expect(wrapped.code).toBe("fetch");
    expect(wrapped.trackId).toBe("t1");
    expect(wrapped.cause).toBe(cause);
  });

  it("passes an existing GenomeDataError through unchanged", () => {
    const original = new GenomeDataError("assembly-mismatch", "nope");
    expect(toGenomeDataError(original, "fetch", "read failed")).toBe(original);
  });

  it("maps AbortError and ERR_ABORTED to the aborted code", () => {
    const abortError = Object.assign(new Error("aborted"), { name: "AbortError" });
    expect(toGenomeDataError(abortError, "fetch", "read failed").code).toBe("aborted");
    const nodeAbort = Object.assign(new Error("aborted"), { code: "ERR_ABORTED" });
    expect(toGenomeDataError(nodeAbort, "parse", "read failed").code).toBe("aborted");
  });
});

describe("OpenCache", () => {
  it("returns one promise for concurrent callers and caches success", async () => {
    const cache = new OpenCache<number>();
    let calls = 0;
    const open = (): Promise<number> => {
      calls += 1;
      return Promise.resolve(calls);
    };
    const first = cache.run(open);
    const second = cache.run(open);
    expect(second).toBe(first);
    await expect(first).resolves.toBe(1);
    // A later caller still gets the cached successful open, never a new one.
    await expect(cache.run(open)).resolves.toBe(1);
    expect(calls).toBe(1);
  });

  it("clears a rejected open so the next caller retries", async () => {
    const cache = new OpenCache<string>();
    let calls = 0;
    const open = (): Promise<string> => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new Error("nope"))
        : Promise.resolve("ok");
    };
    const first = cache.run(open);
    const shared = cache.run(open);
    expect(shared).toBe(first);
    await expect(first).rejects.toThrow("nope");
    await expect(cache.run(open)).resolves.toBe("ok");
    expect(calls).toBe(2);
  });
});

describe("resolveRegion", () => {
  it("resolves an alias inside the assembly", () => {
    expect(
      resolveRegion(assembly, { assemblyKey: "v5.0", refName: "1", start: 3, end: 9 }),
    ).toEqual({ refName: "chr01", start: 3, end: 9 });
  });

  it("rejects a foreign assembly key", () => {
    expect(() =>
      resolveRegion(assembly, { assemblyKey: "v4.0", refName: "chr01", start: 0, end: 1 }),
    ).toThrowError(/does not match/);
  });

  it("rejects an unknown reference name", () => {
    expect(() =>
      resolveRegion(assembly, { assemblyKey: "v5.0", refName: "chr99", start: 0, end: 1 }),
    ).toThrowError(/Unknown reference/);
  });

  it("rejects malformed coordinates", () => {
    expect(() =>
      resolveRegion(assembly, { assemblyKey: "v5.0", refName: "chr01", start: 5, end: 2 }),
    ).toThrowError(/Invalid region/);
    expect(() =>
      resolveRegion(assembly, { assemblyKey: "v5.0", refName: "chr01", start: 0.5, end: 2 }),
    ).toThrowError(/Invalid region/);
  });

  it("accepts an empty region", () => {
    expect(
      resolveRegion(assembly, { assemblyKey: "v5.0", refName: "chr01", start: 4, end: 4 }),
    ).toEqual({ refName: "chr01", start: 4, end: 4 });
  });
});
