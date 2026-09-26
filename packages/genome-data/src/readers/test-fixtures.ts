import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { MemoryFileProvider } from "../file-provider";
import { uriLocation } from "../location";

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
