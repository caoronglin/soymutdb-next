import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const testDirectory = dirname(fileURLToPath(import.meta.url));
const sourceDirectory = resolve(testDirectory, "../../src");
const facadePath = resolve(sourceDirectory, "lib/antd.ts");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "__tests__" ? [] : sourceFiles(path);
    }
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

describe("Ant Design import contract", () => {
  it("keeps application code off the root antd re-export graph", () => {
    const rootImports = sourceFiles(sourceDirectory)
      .filter((path) => path !== facadePath)
      .filter((path) => /from\s+["']antd["']/.test(readFileSync(path, "utf8")))
      .map((path) => relative(sourceDirectory, path));

    expect(rootImports).toEqual([]);

    const facade = readFileSync(facadePath, "utf8");
    expect(facade).toContain('from "antd/es/table"');
    expect(facade).toContain('from "antd/es/theme"');
    expect(facade).not.toMatch(/from\s+["']antd["']/);
  });
});
