#!/usr/bin/env node
/** Enforce the approved React-only workspace, beyond the shipped entry graph. */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const retiredPackage = /^(?:vue(?:-.+)?|@vue\/.+|pinia|antdv-next|@vitejs\/plugin-vue|@tanstack\/vue-query|@soymutdb\/(?:ui-vue|genome-view))$/;
const importPattern = /(?:from\s*|import\s*|require\s*\(\s*)["']([^"']+)["']/g;

function sourceFiles(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === "dist" || entry.name === ".umi") return [];
    const path = resolve(dir, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : entry.isFile() ? [path] : [];
  });
}

export function inspectRetirement(root = ROOT) {
  const problems = [];
  const packages = resolve(root, "packages");
  for (const legacy of ["ui-vue", "genome-view"]) {
    if (existsSync(resolve(packages, legacy))) problems.push(`retired workspace package remains: packages/${legacy}`);
  }
  const roots = ["apps/web/src", "apps/admin/src", "apps/jbrowse/src", "packages"];
  for (const name of roots) {
    for (const file of sourceFiles(resolve(root, name))) {
      const label = relative(root, file);
      if (file.endsWith(".vue")) problems.push(`${label}: Vue component remains`);
      if (!/\.(?:ts|tsx|js|jsx)$/.test(file) || file.endsWith(".d.ts")) continue;
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(importPattern)) {
        if (retiredPackage.test(match[1]) || match[1].endsWith(".vue")) {
          problems.push(`${label}: imports ${match[1]}`);
        }
      }
    }
  }
  for (const name of ["apps/web", "apps/admin", "apps/jbrowse", ...readdirSync(packages, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => `packages/${entry.name}`)]) {
    const manifest = resolve(root, name, "package.json");
    if (!existsSync(manifest)) continue;
    const packageJson = JSON.parse(readFileSync(manifest, "utf8"));
    for (const key of ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]) {
      for (const dependency of Object.keys(packageJson[key] ?? {})) {
        if (retiredPackage.test(dependency)) problems.push(`${name}/package.json: ${key}.${dependency}`);
      }
    }
  }
  const catalog = readFileSync(resolve(root, "pnpm-workspace.yaml"), "utf8");
  for (const line of catalog.split("\n")) {
    const match = line.match(/^\s{2}['"]?([^'":]+)['"]?:\s/);
    if (match && retiredPackage.test(match[1])) problems.push(`pnpm-workspace.yaml: ${match[1]}`);
  }
  const lock = readFileSync(resolve(root, "pnpm-lock.yaml"), "utf8");
  for (const line of lock.split("\n")) {
    if (/^\s{2}['"]?(?:@vue\/|@vitejs\/plugin-vue@|@tanstack\/vue-query@|antdv-next@|pinia@|vue@|vue-router@|vue-demi@|vue-tsc@)/.test(line)) {
      problems.push(`pnpm-lock.yaml: ${line.trim()}`);
    }
  }
  return problems;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const problems = inspectRetirement();
  for (const problem of problems) console.error(problem);
  console.log(`React-only retirement: ${problems.length === 0 ? "PASS" : `FAIL (${problems.length})`}`);
  process.exitCode = problems.length === 0 ? 0 : 1;
}
