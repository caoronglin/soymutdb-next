/**
 * Vue-retirement contract for the standalone genome browser.
 *
 * The repository still *contains* the legacy Vue shell (`src/App.vue`,
 * `src/main.ts`, the Vue components under `src/components/`) and the Vue
 * `@soymutdb/genome-view` package, because final removal is gated on React
 * parity plus deployed E2E acceptance.
 *
 * What must hold *now* is stronger than "Umi points at the React entry": the
 * whole module graph reachable from the shipped entry must be free of Vue. If a
 * React file ever re-imports a `.vue` component or the Vue genome-view package,
 * the migration has silently regressed — and it would only show up at runtime,
 * as a mounted-but-unstyled or duplicate browser.
 *
 * This walks the import graph from `src/umi-entry.tsx` and asserts the closure
 * contains no `.vue` file, no `@soymutdb/genome-view` import, and no `vue`
 * runtime import. `@soymutdb/genome-view-model` is deliberately allowed: it is
 * the framework-neutral model package both shells share.
 *
 * Run with: node --test vue-retirement-contract.test.mjs
 */
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  FORBIDDEN_VUE_PACKAGES,
  collectGraph,
  isAllowedLookalike,
} from "../../scripts/react-entry-graph.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const ENTRY = resolve(root, "src/umi-entry.tsx");
const graph = await collectGraph(ENTRY, root);

test("the shipped entry still resolves to the React shell", () => {
  const entrySpecifiers = graph.get(ENTRY) ?? [];
  assert.ok(
    entrySpecifiers.includes("./react-app"),
    `umi-entry must import ./react-app; got ${JSON.stringify(entrySpecifiers)}`,
  );
  assert.ok(
    [...graph.keys()].some((file) => file.endsWith("src/App.tsx")),
    "the React shell must be reachable from the entry",
  );
});

test("no reachable module imports a .vue file", () => {
  const offenders = [];
  for (const [file, specifiers] of graph) {
    for (const specifier of specifiers) {
      if (specifier.endsWith(".vue")) offenders.push(`${file} -> ${specifier}`);
    }
  }
  assert.deepEqual(offenders, [], `Vue components reachable from the entry: ${offenders}`);
});

test("no reachable module imports the Vue genome-view package or the Vue runtime", () => {
  const offenders = [];
  for (const [file, specifiers] of graph) {
    for (const specifier of specifiers) {
      if (isAllowedLookalike(specifier)) continue;
      const matched = FORBIDDEN_VUE_PACKAGES.find(
        (pkg) => specifier === pkg || specifier.startsWith(`${pkg}/`),
      );
      if (matched) offenders.push(`${file} -> ${specifier}`);
    }
  }
  assert.deepEqual(offenders, [], `Vue imports reachable from the entry: ${offenders}`);
});

test("the retired Vue entry files are not part of the graph", () => {
  const files = [...graph.keys()];
  assert.ok(
    !files.some((file) => file.endsWith("src/App.vue")),
    "src/App.vue must not be reachable from the shipped entry",
  );
  assert.ok(
    !files.some((file) => file.endsWith("src/main.ts")),
    "src/main.ts must not be reachable from the shipped entry",
  );
});

test("the shared model package is still reachable or simply unused", () => {
  // Guard *for* the allowed package: if a future change drops
  // `genome-view-model` from both shells the allow-list above would silently
  // stop mattering, so assert the allow-list does not accidentally match a
  // forbidden package.
  for (const pkg of FORBIDDEN_VUE_PACKAGES) {
    assert.ok(!isAllowedLookalike(pkg), `${pkg} must not be on the allowed list`);
  }
  assert.ok(isAllowedLookalike("@soymutdb/genome-view-model"));
  assert.ok(isAllowedLookalike("@soymutdb/genome-view-model/intervals"));
});
