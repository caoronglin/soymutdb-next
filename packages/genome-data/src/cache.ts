/**
 * Minimal recency-ordered cache. Kept dependency-free so the data layer stays
 * framework-neutral and trivially testable.
 */
export class LruCache<K, V> {
  private readonly entries = new Map<K, V>();

  constructor(private readonly capacity = 32) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new RangeError("LruCache capacity must be a positive integer");
    }
  }

  get(key: K): V | undefined {
    const value = this.entries.get(key);
    if (value === undefined) return undefined;
    // Re-insert to mark as most-recently used.
    this.entries.delete(key);
    this.entries.set(key, value);
    return value;
  }

  /** Returns the evicted value, if the insertion exceeded capacity. */
  set(key: K, value: V): V | undefined {
    if (this.entries.has(key)) this.entries.delete(key);
    this.entries.set(key, value);
    if (this.entries.size > this.capacity) {
      const oldest = this.entries.keys().next().value as K | undefined;
      if (oldest !== undefined) {
        const evicted = this.entries.get(oldest);
        this.entries.delete(oldest);
        return evicted;
      }
    }
    return undefined;
  }

  has(key: K): boolean {
    return this.entries.has(key);
  }

  delete(key: K): boolean {
    return this.entries.delete(key);
  }

  get size(): number {
    return this.entries.size;
  }

  clear(): void {
    this.entries.clear();
  }
}
