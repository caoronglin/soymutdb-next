import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const appSource = await readFile(new URL("./src/App.tsx", import.meta.url), "utf8");
const mainSource = await readFile(new URL("./src/main.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("./src/index.css", import.meta.url), "utf8");
const packageJson = JSON.parse(
  await readFile(new URL("./package.json", import.meta.url), "utf8"),
);
const tsconfig = await readFile(new URL("./tsconfig.json", import.meta.url), "utf8");

test("JBrowse uses Ant Design 6 through one provider", () => {
  assert.match(appSource, /from "antd"/);
  assert.match(mainSource, /DesignSystemProvider/);
  assert.equal(packageJson.dependencies.antd, "catalog:");
});

test("JBrowse has no legacy shared UI dependency or source alias", () => {
  for (const source of [appSource, mainSource, styles, tsconfig]) {
    assert.doesNotMatch(source, /@soymutdb\/ui/);
  }
  assert.equal(packageJson.dependencies["@soymutdb/ui"], undefined);
});
