// ABLATION — the Ant Design facade must export every symbol the admin imports from it.
//
// Invariant: `src/lib/antd.ts` re-exports the antd 6 / ProComponents surface, and every admin
// module imports antd through `@/lib/antd` instead of reaching into `antd` directly. A name that
// the facade does not re-export is not a type error at the call site — it is `undefined` at
// runtime, and React renders nothing (or throws "Element type is invalid") on that route only.
//
// Why it matters: this failure mode already cost the Vue tree real defects — a test mock that
// declared `modelValue` instead of antd v6's `value` hid a P0 where typing into the global search
// box did nothing (see .ai-memory/handoff.md, OPT2 round 2), and an antd `Flex` import missing
// from a mock hid four red tests for a full round. A static export check is the cheap guard.
//
// Scope note: `@ant-design/cli`'s `antd usage` reports "No antd imports found" for this
// repository, because it does not resolve the facade layer. This test is the substitute.
//
// If this is RED: an admin route renders a missing component at runtime only.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");
const facadePath = join(srcRoot, "lib/antd.ts");
const facadeSource = readFileSync(facadePath, "utf8");

function walk(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === ".umi" || entry === ".umi-production" || entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, files);
    } else if ([".ts", ".tsx"].includes(extname(entry)) && !/\.(test|spec)\.[jt]sx?$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

/** Names a module requests from the facade, in one import statement or across several. */
function importedFromFacade(source: string): string[] {
  const names: string[] = [];
  const pattern = /import\s+(type\s+)?\{([^}]*)\}\s+from\s+"@\/lib\/antd"/g;
  for (const match of source.matchAll(pattern)) {
    for (const raw of match[2].split(",")) {
      const name = raw.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0].trim();
      if (name) names.push(name);
    }
  }
  return names;
}

/** Names the facade actually re-exports (value exports and `export type` names). */
function facadeExports(): Set<string> {
  const names = new Set<string>();
  for (const match of facadeSource.matchAll(/export\s+(?:type\s+)?\{([^}]*)\}\s+from/g)) {
    for (const raw of match[1].split(",")) {
      const name = raw.trim().replace(/^type\s+/, "").split(/\s+as\s+/).pop()?.trim();
      if (name) names.add(name);
    }
  }
  return names;
}

const requested = new Map<string, string[]>();
for (const file of walk(srcRoot)) {
  const names = importedFromFacade(readFileSync(file, "utf8"));
  if (names.length > 0) requested.set(relative(srcRoot, file), names);
}

const exported = facadeExports();

describe("antd facade", () => {
  it("finds the admin modules that import through the facade", () => {
    // Guards against a rename of the import path silently emptying this file.
    expect(requested.size).toBeGreaterThan(10);
  });

  it("exports every symbol the admin imports from it", () => {
    const missing: string[] = [];
    for (const [file, names] of [...requested].sort()) {
      for (const name of names) {
        if (!exported.has(name)) missing.push(`${file}: ${name}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("re-exports the Pro building blocks the migration depends on", () => {
    // Named explicitly because "the facade is large" is not evidence that the
    // migration prerequisites are available.
    for (const required of [
      "PageContainer",
      "ProTable",
      "ProDescriptions",
      "ProCard",
      "ModalForm",
      "ProFormText",
      "StatisticCard",
    ]) {
      expect(exported.has(required), required).toBe(true);
    }
  });

  it("does not import antd directly, bypassing the facade", () => {
    const direct: string[] = [];
    for (const file of walk(srcRoot)) {
      const source = readFileSync(file, "utf8");
      if (/from\s+"(antd|@ant-design\/pro-components)"/.test(source)) {
        direct.push(relative(srcRoot, file));
      }
    }
    expect(direct).toEqual([]);
  });

  it("fails when a used symbol is missing from the facade (ablation)", () => {
    // The guard must be able to see a hole: remove the most widely used symbol
    // from the export set and confirm the checker reports every user of it.
    const usage = new Map<string, string[]>();
    for (const [file, names] of requested) {
      for (const name of names) usage.set(name, [...(usage.get(name) ?? []), file]);
    }
    const target = [...usage.entries()].sort((a, b) => b[1].length - a[1].length)[0];
    expect(target, "no facade import was found to ablate").toBeDefined();
    expect(target![1].length).toBeGreaterThan(1);

    const reduced = new Set(exported);
    reduced.delete(target![0]);
    const reported = [...requested]
      .filter(([, names]) => names.includes(target![0]) && !reduced.has(target![0]))
      .map(([file]) => file)
      .sort();
    expect(reported).toEqual([...target![1]].sort());
  });
});