/**
 * Vue-shell contract for the standalone genome browser.
 *
 * Guards the React -> Vue port: the Vue entry must not pull React, it must go
 * through the shared Vue design-system facade, it must render the Vue genome
 * view, and the HTML entry must point at the Vue module.
 *
 * Run with: node --test antd-migration-contract.test.mjs
 */
import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import { test } from "node:test";

const root = new URL("./", import.meta.url);

async function read(relative) {
  return readFile(new URL(relative, root), "utf8");
}

const componentNames = (await readdir(new URL("./src/components", root))).filter((name) =>
  name.endsWith(".vue"),
);
const shellFiles = [
  "src/main.ts",
  "src/App.vue",
  ...componentNames.map((name) => `src/components/${name}`),
];
const sources = Object.fromEntries(
  await Promise.all(shellFiles.map(async (file) => [file, await read(file)])),
);
const indexHtml = await read("index.html");

/** Any React / JBrowse-React module specifier in an import or require. */
const REACT_IMPORT =
  /(?:from\s*|import\s*\(\s*|require\s*\(\s*)["'](?:react|react-dom|react-dom\/client|react-i18next|@tanstack\/react-query|lucide-react|@jbrowse\/[^"']*)["']/;

test("Vue shell has no React or JBrowse-React import", () => {
  for (const [file, source] of Object.entries(sources)) {
    assert.doesNotMatch(source, REACT_IMPORT, `${file} must not import React`);
    assert.doesNotMatch(
      source,
      /from\s*["']antd["']/,
      `${file} must not import antd directly`,
    );
  }
});

test("Vue shell uses the shared Vue design-system facade", () => {
  const app = sources["src/App.vue"];
  assert.match(app, /from\s*["']@soymutdb\/ui-vue["']/);
  assert.match(app, /createThemeConfig/);
  assert.match(app, /ConfigProvider/);
});

test("Vue shell renders the Vue genome view", () => {
  const app = sources["src/App.vue"];
  assert.match(app, /from\s*["']@soymutdb\/genome-view["']/);
  assert.match(app, /GenomeBrowser/);
  assert.match(sources["src/main.ts"], /registerDefaultTrackRenderers/);
});

test("index.html loads the Vue entry and drops the React entry", () => {
  assert.match(indexHtml, /<script[^>]*type="module"[^>]*src="\/src\/main\.ts"/);
  assert.doesNotMatch(indexHtml, /main\.tsx/);
});

test("React shell files are removed", async () => {
  for (const removed of ["src/App.tsx", "src/main.tsx", "src/design-system-provider.tsx"]) {
    await assert.rejects(access(new URL(removed, root)), `${removed} should be deleted`);
  }
});
