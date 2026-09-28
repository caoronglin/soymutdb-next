#!/usr/bin/env node
/**
 * Vue-retirement check: no shipped React/Umi entry may reach Vue.
 *
 * Walks the import graph from each app's Umi entry and fails when the closure
 * contains a `.vue` file, a Vue package, or the retired Vue entry files
 * (`src/App.vue`, `src/main.ts`). Also reports the graph size, so a walker that
 * silently stops early (and therefore passes vacuously) is visible in the
 * output rather than hidden behind a green result.
 *
 * Usage (repo root):
 *   node scripts/check-react-entry-graph.mjs
 *   node scripts/check-react-entry-graph.mjs --json
 *
 * Exit codes: 0 clean, 1 a Vue import was reachable, 2 the check could not run.
 */
import { relative } from "node:path";
import { fileURLToPath } from "node:url";

import { REACT_APPS, appDirFor, inspectApp } from "./react-entry-graph.mjs";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const asJson = process.argv.includes("--json");

/** A graph smaller than this is suspiciously small for a real app entry. */
const MIN_EXPECTED_GRAPH = 3;

const results = [];
let failed = false;

for (const app of REACT_APPS) {
  let inspected;
  try {
    inspected = await inspectApp({
      appDir: appDirFor(repoRoot, app),
      entry: app.entry,
    });
  } catch (error) {
    results.push({ app: app.name, error: String(error) });
    failed = true;
    continue;
  }

  const rel = (file) => relative(repoRoot, file);
  const problems = [
    ...inspected.vueFiles.map((hit) => `${rel(hit.from)} imports ${hit.specifier}`),
    ...inspected.vueImports.map((hit) => `${rel(hit.from)} imports ${hit.specifier}`),
    ...inspected.retiredEntryReached.map((file) => `${rel(file)} is reachable`),
  ];

  const tooSmall = inspected.graph.size < MIN_EXPECTED_GRAPH;
  if (tooSmall) {
    problems.push(
      `entry graph has only ${inspected.graph.size} module(s) — the walker may have stopped early`,
    );
  }

  if (problems.length > 0) failed = true;
  results.push({
    app: app.name,
    entry: rel(inspected.entry),
    modules: inspected.graph.size,
    problems,
  });
}

if (asJson) {
  process.stdout.write(`${JSON.stringify({ ok: !failed, results }, null, 2)}\n`);
} else {
  for (const result of results) {
    if (result.error) {
      console.error(`FAIL  ${result.app}: ${result.error}`);
      continue;
    }
    const status = result.problems.length === 0 ? "PASS" : "FAIL";
    console.log(
      `${status}  ${result.app.padEnd(7)} entry=${result.entry} modules=${result.modules}`,
    );
    for (const problem of result.problems) {
      console.log(`        ${problem}`);
    }
  }
  console.log(
    failed
      ? "Vue-retirement check: FAILED — a shipped entry reaches Vue source"
      : "Vue-retirement check: OK",
  );
}

process.exit(failed ? 1 : 0);
