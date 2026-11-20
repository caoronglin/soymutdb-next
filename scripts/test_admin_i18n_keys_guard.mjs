#!/usr/bin/env node
/**
 * Ablation tests for `check-admin-i18n-keys.mjs`.
 *
 * The guard exists because a `t()` key that was never registered fails
 * silently: i18next falls back to `defaultValue`, every other gate stays
 * green, and a zh console quietly prints English. "The guard passes on the
 * repository" is therefore not evidence — each test below feeds it a
 * synthetic tree and asserts it *fails*, on the exact class of bug it was
 * written for.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const GUARD = path.join(ROOT, "scripts", "check-admin-i18n-keys.mjs");

/**
 * Build a throwaway tree holding a locale pair plus one admin source file, run
 * the guard against it, and return `{ code, output }`.
 */
function run({
  zh,
  en,
  source,
  sourcePath = "apps/admin/src/page.tsx",
  bootstrap = null,
  resources = null,
}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "admin-i18n-"));
  try {
    for (const [lang, catalog] of Object.entries({ zh, en })) {
      const dir = path.join(tmp, "packages", "i18n-core", "src", "locales", lang);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "common.json"), JSON.stringify(catalog, null, 2), "utf8");
    }
    const file = path.join(tmp, sourcePath);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, source, "utf8");
    if (bootstrap !== null) {
      const bootstrapFile = path.join(tmp, "apps/web/src/lib/i18n.ts");
      fs.mkdirSync(path.dirname(bootstrapFile), { recursive: true });
      fs.writeFileSync(bootstrapFile, bootstrap, "utf8");
    }
    if (resources !== null) {
      const resourcesFile = path.join(tmp, "apps/web/src/lib/i18n-resources.ts");
      fs.mkdirSync(path.dirname(resourcesFile), { recursive: true });
      fs.writeFileSync(resourcesFile, resources, "utf8");
    }
    try {
      const stdout = execFileSync("node", [GUARD, "--root", tmp], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      });
      return { code: 0, output: stdout };
    } catch (error) {
      return { code: error.status ?? 1, output: `${error.stdout ?? ""}${error.stderr ?? ""}` };
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

const failures = [];

function expect(condition, message) {
  if (!condition) failures.push(message);
}

// 1. Baseline: a registered key in both catalogs passes.
{
  const result = run({
    zh: { admin: { greeting: "你好" } },
    en: { admin: { greeting: "Hello" } },
    source: 'export const x = () => t("admin.greeting");\n',
  });
  expect(result.code === 0, `baseline should pass, got ${result.code}: ${result.output}`);
}

// 2. The original defect: a key that is in neither catalog.
{
  const result = run({
    zh: { admin: { greeting: "你好" } },
    en: { admin: { greeting: "Hello" } },
    source: 'export const x = () => t("admin.status.releaseDraft", { defaultValue: "Draft" });\n',
  });
  expect(result.code === 1, "an unregistered literal key must fail");
  expect(
    result.output.includes("admin.status.releaseDraft"),
    `the report must name the missing key, got: ${result.output}`,
  );
  expect(
    result.output.includes("missing in zh") && result.output.includes("missing in en"),
    "the report must name both catalogs",
  );
}

// 3. Half-translated: registered in en, forgotten in zh (what a zh console sees).
{
  const result = run({
    zh: { admin: {} },
    en: { admin: { only: "English only" } },
    source: 'export const x = () => t("admin.only");\n',
  });
  expect(result.code === 1, "a key missing from one catalog must fail");
  expect(result.output.includes("missing in zh"), "the report must name zh");
}

// 4. Catalog drift: zh has a key en never got.
{
  const result = run({
    zh: { admin: { both: "都有", extra: "只有中文" } },
    en: { admin: { both: "Both" } },
    source: 'export const x = () => t("admin.both");\n',
  });
  expect(result.code === 1, "catalog drift must fail");
  expect(result.output.includes("admin.extra"), "the report must name the drifted key");
}

// 5. The dynamic-key defect: a hand-built key whose namespace does not exist.
//    `admin.content.type_${type}` builds `admin.content.type_news`, and neither
//    the prefix nor the built name is registered.
{
  const result = run({
    zh: { admin: { content: { title: "内容" } } },
    en: { admin: { content: { title: "Content" } } },
    source: "export const x = (type: string) => t(`admin.content.type_${type}`);\n",
  });
  expect(result.code === 1, "an unregistered dynamic namespace must fail");
  expect(
    result.output.includes("admin.content.type"),
    `the report must name the namespace, got: ${result.output}`,
  );
}

// 6. ...and the corrected form passes once the namespace exists.
{
  const result = run({
    zh: { admin: { content: { type: { news: "新闻" } } } },
    en: { admin: { content: { type: { news: "News" } } } },
    source: "export const x = (type: string) => t(`admin.content.type.${type}`);\n",
  });
  expect(result.code === 0, `a registered dynamic namespace should pass, got: ${result.output}`);
}

// 7. `labelKey:` data tables are checked too — that is how the ten
//    `admin.status.*` keys hid: they were never called with a literal `t()`.
{
  const result = run({
    zh: { admin: {} },
    en: { admin: {} },
    source: 'const config = { labelKey: "admin.status.taskRunning" };\n',
  });
  expect(result.code === 1, "labelKey entries must be checked");
  expect(result.output.includes("admin.status.taskRunning"), "the report must name the labelKey");
}

// 8. Test files are not scanned: a test may legitimately reference a key that
//    no component uses.
{
  const result = run({
    zh: { admin: {} },
    en: { admin: {} },
    source: 'export const x = () => t("admin.missing");\n',
    sourcePath: "apps/admin/src/page.test.tsx",
  });
  expect(result.code === 0, `test files should be skipped, got: ${result.output}`);
}

// 9. A key registered only in the portal-only runtime overlay must pass.
//    The app merges these bundles in `lib/i18n.ts`; a guard that reads only
//    `common.json` would reject it, which is exactly how `tools.sequence.*`
//    shipped 178 false positives while the UI rendered the right copy.
{
  const overlay = `export const EXTRA_RESOURCES: Record<string, unknown> = {
  en: { tools: { sequence: { title: "Sequence Toolkit" } } },
  zh: { tools: { sequence: { title: "序列工具" } } },
};
`;
  const bootstrap = `import { EXTRA_RESOURCES } from "./i18n-resources";
export function init(): void {
  for (const [lng, bundle] of Object.entries(EXTRA_RESOURCES)) void [lng, bundle];
}
`;
  const args = {
    zh: { admin: { greeting: "你好" } },
    en: { admin: { greeting: "Hello" } },
    source: 'export const x = () => t("tools.sequence.title");\n',
    bootstrap,
    resources: overlay,
  };
  const result = run(args);
  expect(result.code === 0, `a runtime-overlay key should pass, got ${result.code}: ${result.output}`);
}

// 10. ...and dropping the overlay from the bootstrap makes it fail again.
//    This pins that the guard reads the composition from `i18n.ts` rather than
//    hardcoding an overlay list that can drift away from the app.
{
  const overlay = `export const EXTRA_RESOURCES: Record<string, unknown> = {
  en: { tools: { sequence: { title: "Sequence Toolkit" } } },
  zh: { tools: { sequence: { title: "序列工具" } } },
};
`;
  const bootstrap = `import { EXTRA_RESOURCES } from "./i18n-resources";
export function init(): void { void EXTRA_RESOURCES; }
`;
  const result = run({
    zh: { admin: { greeting: "你好" } },
    en: { admin: { greeting: "Hello" } },
    source: 'export const x = () => t("tools.sequence.title");\n',
    bootstrap,
    resources: overlay,
  });
  expect(result.code === 1, "an overlay the app no longer merges must not satisfy the guard");
  expect(
    result.output.includes("tools.sequence.title"),
    `the report must name the unregistered key, got: ${result.output}`,
  );
}

// 11. Same shape through the dynamic-prefix path: a namespace that exists only
//     in the runtime overlay is a valid `t("prefix." + value)` target.
{
  const overlay = `export const TOOLS_RESOURCES: Record<string, unknown> = {
  en: { tools: { sequence: { error: { unknown: "Unknown" } } } },
  zh: { tools: { sequence: { error: { unknown: "未知" } } } },
};
`;
  const bootstrap = `import { TOOLS_RESOURCES } from "./i18n-resources";
export function init(): void {
  for (const [lng, bundle] of Object.entries(TOOLS_RESOURCES)) void [lng, bundle];
}
`;
  const result = run({
    zh: { admin: { greeting: "你好" } },
    en: { admin: { greeting: "Hello" } },
    source: 'export const x = (code: string) => t(`tools.sequence.error.${code}`);\n',
    bootstrap,
    resources: overlay,
  });
  expect(result.code === 0, `a runtime-overlay namespace should pass, got: ${result.output}`);
}

if (failures.length > 0) {
  console.error(`admin i18n key guard ablation FAILED (${failures.length}):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log("admin i18n key guard ablation OK (11 scenarios)");
