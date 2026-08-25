import { existsSync, readFileSync, readdirSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ADMIN_ROOT = resolve(process.cwd());
const FORBIDDEN_REFERENCES = [
  ["@soymutdb", "ui"].join("/"),
  ["packages", "ui"].join("/"),
];
const TEXT_EXTENSIONS = new Set([".css", ".json", ".ts", ".tsx"]);

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collectSourceFiles(path);
    return TEXT_EXTENSIONS.has(extname(entry.name)) ? [path] : [];
  });
}

describe("Admin UI dependency contract", () => {
  it("keeps Admin independent from the legacy shared UI package", () => {
    const files = [
      ...collectSourceFiles(resolve(ADMIN_ROOT, "src")),
      resolve(ADMIN_ROOT, "package.json"),
      resolve(ADMIN_ROOT, "tsconfig.json"),
      // The canonical Admin Dockerfile moved to infra/docker/Dockerfile.admin
      // (apps/admin/Dockerfile was removed in the toolchain consolidation).
      resolve(ADMIN_ROOT, "../../infra/docker/Dockerfile.admin"),
      resolve(ADMIN_ROOT, "vitest.config.ts"),
      // Skip files that are absent so a moved/removed artifact does not make
      // the whole contract fail with ENOENT; the scan covers what exists.
    ].filter((path) => existsSync(path));
    const violations = files.flatMap((path) => {
      const source = readFileSync(path, "utf8");
      return FORBIDDEN_REFERENCES.some((reference) => source.includes(reference))
        ? [relative(ADMIN_ROOT, path)]
        : [];
    });

    expect(violations).toEqual([]);
  });
});
