/**
 * Tests for the shared React-entry import-graph walker and the cross-app
 * Vue-retirement check.
 *
 * The risk with a reachability check is that it passes *vacuously*: if the
 * walker stops one hop early, or the entry path is wrong, it reports a clean
 * graph without having inspected anything. These tests pin the walker's
 * behaviour against a synthetic Vue entry, so a broken walker fails here
 * instead of silently approving the retirement.
 *
 * Run with: node --test scripts/check-react-entry-graph.test.mjs
 */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { test } from "node:test";

import {
  ALLOWED_VUE_LOOKALIKES,
  FORBIDDEN_VUE_PACKAGES,
  REACT_APPS,
  appDirFor,
  collectGraph,
  inspectApp,
  isAllowedLookalike,
  resolveRelative,
} from "./react-entry-graph.mjs";

const execFileAsync = promisify(execFile);
const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));

test("every declared React app has an entry file that exists", async () => {
  for (const app of REACT_APPS) {
    const inspected = await inspectApp({
      appDir: appDirFor(repoRoot, app),
      entry: app.entry,
    });
    // A real app entry pulls in more than a couple of modules; a tiny graph
    // means the walk stopped early and the PASS would be meaningless.
    assert.ok(
      inspected.graph.size >= 3,
      `${app.name}: entry graph has only ${inspected.graph.size} module(s)`,
    );
  }
});

test("no shipped React entry graph reaches Vue", async () => {
  for (const app of REACT_APPS) {
    const inspected = await inspectApp({
      appDir: appDirFor(repoRoot, app),
      entry: app.entry,
    });
    assert.deepEqual(inspected.vueFiles, [], `${app.name}: .vue files reachable`);
    assert.deepEqual(inspected.vueImports, [], `${app.name}: Vue packages reachable`);
    assert.deepEqual(
      inspected.retiredEntryReached,
      [],
      `${app.name}: retired Vue entry reachable`,
    );
  }
});

test("the walker is load-bearing: a synthetic Vue entry is detected", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "soymutdb-vue-guard-"));
  try {
    mkdirSync(resolve(root, "src"));
    writeFileSync(resolve(root, "src/entry.ts"),
      'import "./Retired.vue";\nimport "vue";\nimport "@soymutdb/genome-view";\n',
    );
    writeFileSync(resolve(root, "src/Retired.vue"), "<template><div /></template>\n");
    const inspected = await inspectApp({ appDir: root, entry: "src/entry.ts" });
    assert.ok(inspected.vueFiles.length > 0, "expected a .vue import");
    assert.ok(inspected.vueImports.some((hit) => hit.specifier === "vue"));
    assert.ok(inspected.vueImports.some((hit) => hit.specifier === "@soymutdb/genome-view"));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("resolveRelative requires the file to exist", () => {
  const root = resolve(repoRoot, "apps/jbrowse");
  const from = resolve(root, "src/react-app.tsx");

  // `./App` resolves to the real `App.tsx`...
  assert.equal(resolveRelative(from, "./App", root), resolve(root, "src/App.tsx"));
  // ...and a non-existent sibling resolves to nothing rather than to a
  // plausible-looking path that would silently end the walk.
  assert.equal(resolveRelative(from, "./DoesNotExist", root), null);
  // Bare package specifiers are not local files.
  assert.equal(resolveRelative(from, "@soymutdb/ui-react", root), null);
  // Paths outside the app root are refused.
  assert.equal(resolveRelative(from, "../../../package.json", root), null);
});

test("the allow-list covers the shared model package and nothing forbidden", () => {
  for (const allowed of ALLOWED_VUE_LOOKALIKES) {
    assert.ok(isAllowedLookalike(allowed));
    assert.ok(isAllowedLookalike(`${allowed}/sub`));
    // The allow-list must not accidentally whitelist a real Vue package.
    assert.ok(!FORBIDDEN_VUE_PACKAGES.includes(allowed));
  }
  for (const forbidden of FORBIDDEN_VUE_PACKAGES) {
    assert.ok(!isAllowedLookalike(forbidden), `${forbidden} must stay forbidden`);
  }
});

test("the CLI reports the graph size so a vacuous pass is visible", async () => {
  const { stdout } = await execFileAsync(
    process.execPath,
    ["scripts/check-react-entry-graph.mjs", "--json"],
    { cwd: repoRoot },
  );
  const payload = JSON.parse(stdout);

  assert.equal(payload.ok, true);
  assert.equal(payload.results.length, REACT_APPS.length);
  for (const result of payload.results) {
    assert.equal(result.problems.length, 0, JSON.stringify(result.problems));
    assert.ok(result.modules >= 3, `${result.app} modules=${result.modules}`);
    assert.ok(result.entry.endsWith("umi-entry.tsx"));
  }
});

test("the CLI exits non-zero when an entry path does not exist", async () => {
  // Point the same code at a missing entry via the module API (the CLI only
  // knows the declared apps), asserting the failure mode is an explicit error
  // rather than a silently-empty graph.
  await assert.rejects(
    () => inspectApp({ appDir: repoRoot, entry: "apps/web/src/nope.tsx" }),
    /entry not found/,
  );
});

test("collectGraph follows a multi-hop chain rather than a single level", async () => {
  const root = resolve(repoRoot, "apps/admin");
  const graph = await collectGraph(resolve(root, "src/umi-entry.tsx"), root);

  // `umi-entry` -> `react-app` -> `App` -> route modules is at least 3 hops.
  const files = [...graph.keys()];
  assert.ok(files.some((file) => file.endsWith("src/umi-entry.tsx")));
  assert.ok(files.some((file) => file.endsWith("src/react-app.tsx")));
  assert.ok(files.some((file) => file.endsWith("src/App.tsx")));
  assert.ok(graph.size > 3, `expected a deep graph, got ${graph.size}`);
});
