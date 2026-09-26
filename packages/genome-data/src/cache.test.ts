import { describe, expect, it } from "vitest";

import { LruCache } from "./cache";

describe("LruCache", () => {
  it("rejects non-positive capacities", () => {
    expect(() => new LruCache(0)).toThrow(RangeError);
    expect(() => new LruCache(-1)).toThrow(RangeError);
  });

  it("evicts the least-recently used entry and returns it", () => {
    const cache = new LruCache<string, number>(2);
    expect(cache.set("a", 1)).toBeUndefined();
    expect(cache.set("b", 2)).toBeUndefined();
    // Touch "a" so "b" becomes the oldest.
    expect(cache.get("a")).toBe(1);
    expect(cache.set("c", 3)).toBe(2);
    expect(cache.has("b")).toBe(false);
    expect(cache.has("a")).toBe(true);
    expect(cache.has("c")).toBe(true);
    expect(cache.size).toBe(2);
  });

  it("refreshes recency on get and replaces existing keys", () => {
    const cache = new LruCache<string, number>(2);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("a", 10);
    expect(cache.get("a")).toBe(10);
    expect(cache.set("c", 3)).toBe(2);
    expect(cache.delete("c")).toBe(true);
    expect(cache.clear()).toBeUndefined();
    expect(cache.size).toBe(0);
  });
});
