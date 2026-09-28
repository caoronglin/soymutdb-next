/**
 * React/Umi migration contract for the standalone genome browser.
 *
 * JBrowse is served by Umi: there is no hand-authored index.html entrypoint.
 * This contract protects the canonical React shell while the repository still
 * contains legacy Vue source files during the staged migration.
 *
 * Run with: node --test antd-migration-contract.test.mjs
 */
import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { test } from "node:test";

const root = new URL("./", import.meta.url);

async function read(relative) {
  return readFile(new URL(relative, root), "utf8");
}

const sources = Object.fromEntries(
  await Promise.all(
    [
      "src/umi-entry.tsx",
      "src/react-app.tsx",
      "src/App.tsx",
      "src/design-system-provider.tsx",
      "config/config.ts",
    ].map(async (file) => [file, await read(file)]),
  ),
);

test("Umi selects the React entrypoint", () => {
  assert.match(sources["config/config.ts"], /component:\s*["']@\/umi-entry["']/);
  assert.doesNotMatch(sources["config/config.ts"], /App\.vue|src\/main\.ts/);
  assert.match(sources["src/umi-entry.tsx"], /from\s+["']\.\/react-app["']/);
  assert.match(sources["src/umi-entry.tsx"], /<ReactApp\s*\/>/);
});

test("React shell crosses the shared Ant Design boundary", () => {
  assert.match(sources["src/react-app.tsx"], /QueryClientProvider/);
  assert.match(sources["src/react-app.tsx"], /DesignSystemProvider/);
  assert.match(sources["src/design-system-provider.tsx"], /@soymutdb\/ui-react/);
  assert.match(sources["src/design-system-provider.tsx"], /ConfigProvider/);
});

test("React shell renders the official JBrowse view and bridge", () => {
  const app = sources["src/App.tsx"];
  assert.match(app, /@jbrowse\/react-linear-genome-view/);
  assert.match(app, /JBrowseLinearGenomeView/);
  assert.match(app, /\.\/bridge/);
  assert.match(app, /postToParent/);
  assert.match(app, /parsePortalMessage/);
});

test("Umi-generated HTML is the only document entrypoint", async () => {
  await assert.rejects(access(new URL("index.html", root)), "source index.html must not be required");
  assert.match(sources["src/react-app.tsx"], /\.\/index\.css/);
});
