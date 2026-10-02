/**
 * Shared React-entry import-graph walker for the Vue-retirement contract.
 *
 * The repository still contains legacy Vue source during the staged migration.
 * Final removal is gated on React parity plus deployed E2E acceptance, so what
 * must hold *now* is that the module graph reachable from each app's **shipped**
 * entry is free of Vue. A React file that re-imports a `.vue` component or a
 * Vue view package would only fail at runtime — as a mounted-but-unstyled view
 * or a duplicate browser — so it is checked statically.
 *
 * `@soymutdb/genome-view-model` is deliberately allowed: it is the
 * framework-neutral model package that both the Vue and React shells consume.
 * `@soymutdb/genome-view` was on this list only while it was a Vue view layer;
 * it has since been rebuilt as a React renderer (`renderGenomeViewSvg` plus
 * React components), and apps/web legitimately imports it. What the check must
 * police is the framework reached through the import, not the package's former
 * name — the `.vue` file rule below still catches a Vue component reappearing
 * inside that package.
 *
 * Exposed as a module so the walker has exactly one implementation, used by both
 * the per-app contract tests and `scripts/check-react-entry-graph.mjs`.
 */
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

/** Matches `from "..."` and bare `import "..."`. */
const IMPORT_RE = /(?:from\s*|import\s*)["']([^"']+)["']/g;

/** Vue packages that must not appear in a shipped entry graph. */
export const FORBIDDEN_VUE_PACKAGES = [
  "vue",
  "vue-router",
  "pinia",
  "@vue/test-utils",
];

/** Packages whose names contain "vue" but are the shared, framework-neutral layer. */
export const ALLOWED_VUE_LOOKALIKES = ["@soymutdb/genome-view-model"];

/** True when *specifier* is an explicitly allowed Vue-lookalike package. */
export function isAllowedLookalike(specifier) {
  return ALLOWED_VUE_LOOKALIKES.some(
    (allowed) => specifier === allowed || specifier.startsWith(`${allowed}/`),
  );
}

/**
 * Resolve a relative specifier to a file that actually exists.
 *
 * Existence is checked rather than inferred from the extension: `./App` has no
 * extension of its own, and a purely lexical check would "resolve" it to a
 * non-existent `App.ts` and stop the walk one hop early — which is exactly how
 * the contract would stop guarding anything.
 */
export function resolveRelative(fromFile, specifier, root) {
  if (!specifier.startsWith(".")) return null;
  const base = resolve(dirname(fromFile), specifier);
  const candidates = [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    `${base}.vue`,
    `${base}.js`,
    `${base}.mjs`,
    resolve(base, "index.ts"),
    resolve(base, "index.tsx"),
  ];
  for (const candidate of candidates) {
    const insideRoot = candidate === root || candidate.startsWith(root + sep);
    if (insideRoot && existsSync(candidate)) return candidate;
  }
  return null;
}

/** Breadth-first walk of the local import graph from *entry*. */
export async function collectGraph(entry, root) {
  const visited = new Map(); // file -> [specifiers]
  const queue = [entry];
  while (queue.length > 0) {
    const file = queue.shift();
    if (visited.has(file)) continue;
    let source;
    try {
      source = await readFile(file, "utf8");
    } catch {
      visited.set(file, []);
      continue;
    }
    const specifiers = [...source.matchAll(IMPORT_RE)].map((match) => match[1]);
    visited.set(file, specifiers);
    for (const specifier of specifiers) {
      const target = resolveRelative(file, specifier, root);
      if (target && !visited.has(target)) queue.push(target);
    }
  }
  return visited;
}

/**
 * Findings for one app: Vue files, Vue packages and the retired entry files that
 * were reached from *entry*.
 *
 * @returns `{ entry, root, graph, vueFiles, vueImports, retiredEntryReached }`
 */
export async function inspectApp({ appDir, entry: entryRelative }) {
  const root = resolve(appDir);
  const entry = resolve(root, entryRelative);
  if (!existsSync(entry)) {
    throw new Error(`entry not found: ${entry}`);
  }
  const graph = await collectGraph(entry, root);

  const vueFiles = [];
  const vueImports = [];
  for (const [file, specifiers] of graph) {
    for (const specifier of specifiers) {
      if (specifier.endsWith(".vue")) {
        vueFiles.push({ from: file, specifier });
        continue;
      }
      if (isAllowedLookalike(specifier)) continue;
      const matched = FORBIDDEN_VUE_PACKAGES.find(
        (pkg) => specifier === pkg || specifier.startsWith(`${pkg}/`),
      );
      if (matched) vueImports.push({ from: file, specifier });
    }
  }

  const retiredEntryReached = [...graph.keys()].filter((file) =>
    /src[\\/](App\.vue|main\.ts)$/.test(file),
  );

  return { entry, root, graph, vueFiles, vueImports, retiredEntryReached };
}

/** The three React/Umi apps and the entry each one actually ships. */
export const REACT_APPS = [
  { name: "web", appDir: "apps/web", entry: "src/umi-entry.tsx" },
  { name: "admin", appDir: "apps/admin", entry: "src/umi-entry.tsx" },
  { name: "jbrowse", appDir: "apps/jbrowse", entry: "src/umi-entry.tsx" },
];

/** Resolve an app directory relative to *baseDir* (usually the repo root). */
export function appDirFor(baseDir, app) {
  return resolve(baseDir, app.appDir);
}

export { dirname, resolve, sep, fileURLToPath };
