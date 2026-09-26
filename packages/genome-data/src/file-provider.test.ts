import { describe, expect, it, vi } from "vitest";

import { GenomeDataError } from "./errors";
import {
  CachingFileProvider,
  MemoryFileProvider,
  UriFileProvider,
} from "./file-provider";
import { uriLocation } from "./location";

describe("MemoryFileProvider", () => {
  it("serves registered bytes and reports unknown locations", async () => {
    const provider = new MemoryFileProvider();
    const location = uriLocation("memory://fixture.txt");
    expect(provider.has(location)).toBe(false);
    provider.add(location, "hello genome");
    expect(provider.has(location)).toBe(true);

    const handle = await provider.open(location);
    expect(await handle.readFile({ encoding: "utf8" })).toBe("hello genome");

    await expect(provider.open(uriLocation("memory://missing.txt"))).rejects.toMatchObject({
      code: "fetch",
    });
  });
});

describe("UriFileProvider", () => {
  it("rejects a non-uri location", async () => {
    const provider = new UriFileProvider();
    await expect(provider.open({ kind: "local", path: "/tmp/x" })).rejects.toBeInstanceOf(
      GenomeDataError,
    );
  });
});

describe("CachingFileProvider", () => {
  it("reuses a handle for the same location and closes evicted handles", async () => {
    const inner = new MemoryFileProvider();
    const a = uriLocation("memory://a");
    const b = uriLocation("memory://b");
    inner.add(a, "a");
    inner.add(b, "b");

    const provider = new CachingFileProvider(inner, 1);
    const first = await provider.open(a);
    expect(await provider.open(a)).toBe(first);

    const closeSpy = vi.spyOn(first, "close");
    // Opening b evicts a's handle from the 1-entry cache.
    await provider.open(b);
    await Promise.resolve();
    expect(closeSpy).toHaveBeenCalled();
  });
});
