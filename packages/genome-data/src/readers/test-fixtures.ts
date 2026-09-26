import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { GenericFilehandle } from "generic-filehandle";

import { MemoryFileProvider, type FileProvider } from "../file-provider";
import { uriLocation, type GenomeLocation } from "../location";

const FIXTURE_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../test/fixtures",
);

/** Build the in-memory location a reader uses for a committed fixture. */
export function fixtureLocation(name: string) {
  return uriLocation("memory://" + name);
}

export function fixtureBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(resolve(FIXTURE_DIR, name)));
}

export function fixtureText(name: string): string {
  return readFileSync(resolve(FIXTURE_DIR, name), "utf8");
}

/**
 * A MemoryFileProvider preloaded with the named fixture files. Tests never
 * touch the network; every byte comes from the committed fixture directory.
 */
export function fixtureProvider(names: readonly string[]): MemoryFileProvider {
  const provider = new MemoryFileProvider();
  for (const name of names) {
    provider.add(fixtureLocation(name), fixtureBytes(name));
  }
  return provider;
}

/**
 * Fails the first `open()` call and delegates every later call to `inner`.
 *
 * This models a transiently unreachable source (or the Retry cycle after one):
 * the first read rejects at the open stage, and a later read must start a fresh
 * open instead of replaying the cached rejection. `openCount` lets a test
 * assert that the retry really re-entered the provider.
 */
export class FailFirstOpenProvider implements FileProvider {
  private attempts = 0;

  constructor(private readonly inner: FileProvider) {}

  get openCount(): number {
    return this.attempts;
  }

  async open(location: GenomeLocation): Promise<GenericFilehandle> {
    this.attempts += 1;
    if (this.attempts === 1) {
      throw new Error("transient open failure");
    }
    return this.inner.open(location);
  }
}
