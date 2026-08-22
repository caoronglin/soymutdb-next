import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

async function sourceFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) return sourceFiles(path);
      return /\.(?:css|ts|tsx)$/.test(entry.name) ? [path] : [];
    }),
  );
  return nested.flat();
}

describe("public portal design-system boundary", () => {
  it("has no legacy shared UI imports, stylesheet, alias, or dependency", async () => {
    const legacyPackage = ["@soymutdb", "ui"].join("/");
    const root = resolve(import.meta.dirname, "../..");
    const files = await sourceFiles(resolve(root, "src"));
    files.push(resolve(root, "package.json"), resolve(root, "tsconfig.json"));

    for (const path of files) {
      expect(await readFile(path, "utf8"), path).not.toContain(legacyPackage);
    }
  });
});
