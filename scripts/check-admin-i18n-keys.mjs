#!/usr/bin/env node
/**
 * Guard: every i18n key the admin console references exists in BOTH catalogs.
 *
 * Why this exists
 * ---------------
 * `check_visible_i18n_react.mjs` catches hardcoded copy. It cannot catch the
 * opposite failure: a `t("admin.status.releaseDraft")` whose key was never
 * registered. i18next then falls back to `defaultValue` (or, with no default,
 * renders the key itself), so a zh console silently prints English -- or
 * `admin.content.type_news` -- and every gate stays green.
 *
 * That is not hypothetical: ten `admin.status.*` keys, three content-tab keys,
 * three media-purpose keys and the release status labels were all missing from
 * both catalogs when this guard was written.
 *
 * What it checks
 * --------------
 * 1. Every literal key passed to `t(...)`, `labelKey:`, or `i18nKey=` under
 *    apps/{admin,web}/src is registered in zh and in en. A key built as
 *    `t("prefix." + value)` or `t(`prefix.${value}`)` is collected as a
 *    namespace requirement: `prefix` must be an object in both catalogs, or
 *    the runtime lookup can only ever miss.
 * 2. zh and en have the same key set (a key added to one catalog only is the
 *    same bug from the other direction).
 *
 * The catalog is not just `common.json`: `lib/i18n.ts` also overlays the
 * portal-only bundles from `lib/i18n-resources.ts` at runtime. The guard reads
 * that file's `Object.entries(...RESOURCES)` calls so its bundle view is the
 * same composition the app uses, instead of a second hardcoded declaration.
 * Node 26 strips the TS types on import; no build or workspace install needed.
 *
 * Exit code 0 when clean, 1 with a per-key report otherwise.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const defaultRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * `--root <dir>` runs the guard over another tree. The ablation test in
 * `scripts/test_admin_i18n_keys_guard.mjs` needs that: a guard that cannot be
 * made to fail is not evidence that it checks anything.
 */
function readRoot() {
  const index = process.argv.indexOf("--root");
  if (index < 0) return defaultRoot;
  const value = process.argv[index + 1];
  if (!value) {
    console.error("--root requires a directory");
    process.exit(2);
  }
  return path.resolve(value);
}

const root = readRoot();
const LOCALES = {
  en: "packages/i18n-core/src/locales/en/common.json",
  zh: "packages/i18n-core/src/locales/zh/common.json",
};
const SOURCE_ROOTS = ["apps/admin/src", "apps/web/src"];

function flatten(value, prefix = "", out = {}) {
  for (const [key, child] of Object.entries(value)) {
    const next = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) flatten(child, next, out);
    else out[next] = child;
  }
  return out;
}

function walk(dir, files = []) {
  if (!fs.existsSync(dir)) return files;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "dist") continue;
      walk(full, files);
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

const catalogs = Object.fromEntries(
  Object.entries(LOCALES).map(([lang, file]) => [
    lang,
    flatten(JSON.parse(fs.readFileSync(path.join(root, file), "utf8"))),
  ]),
);

/**
 * Merge the portal-only overlays `lib/i18n.ts` applies at runtime. Reading the
 * composition from the bootstrap keeps this guard and the app on one truth:
 * add a resource bundle there and both see it, drop one and both lose it.
 */
async function mergeRuntimeBundles() {
  const bootstrap = path.join(root, "apps/web/src/lib/i18n.ts");
  const resources = path.join(root, "apps/web/src/lib/i18n-resources.ts");
  if (!fs.existsSync(bootstrap) || !fs.existsSync(resources)) return;
  const source = fs.readFileSync(bootstrap, "utf8");
  const names = [
    ...source.matchAll(/Object\.entries\(([A-Z_]*RESOURCES)\)/g),
  ].map((match) => match[1]);
  if (names.length === 0) return;
  const module = await import(pathToFileURL(resources).href);
  for (const name of names) {
    const bundles = module[name];
    if (!bundles) {
      console.error(`admin i18n key check FAILED: i18n.ts overlays ${name}, but it is not exported`);
      process.exit(1);
    }
    for (const [lang, bundle] of Object.entries(bundles)) {
      if (catalogs[lang]) Object.assign(catalogs[lang], flatten(bundle));
    }
  }
}

await mergeRuntimeBundles();

/** @type {Map<string, Set<string>>} key/prefix -> files that reference it */
const literal = new Map();
/** @type {Map<string, Set<string>>} */
const dynamic = new Map();

function record(map, key, file) {
  if (!map.has(key)) map.set(key, new Set());
  map.get(key).add(path.relative(root, file));
}

for (const file of SOURCE_ROOTS.flatMap((dir) => walk(path.join(root, dir)))) {
  const source = fs.readFileSync(file, "utf8");
  // t("a.b.c") / t('a.b.c') — also `labelKey: "a.b"` and `i18nKey="a.b"`.
  for (const match of source.matchAll(/\bt\(\s*["']([A-Za-z0-9_.@-]+)["']/g)) {
    record(literal, match[1], file);
  }
  for (const match of source.matchAll(/\b(?:labelKey|i18nKey)\s*[:=]\s*["']([A-Za-z0-9_.@-]+)["']/g)) {
    record(literal, match[1], file);
  }
  // t("a.b." + value) / t(`a.b.${value}`) - the tail is decided at runtime, so
  // only the static prefix can be checked: it must be a real object in both
  // catalogs, otherwise the lookup can only ever miss. This is how
  // `admin.content.type_${type}` survived: it is not a prefix of anything, and
  // the string "type_news" it builds by hand does not exist either.
  for (const match of source.matchAll(/\bt\(\s*["']([A-Za-z0-9_.@-]+?)\.?["']\s*\+/g)) {
    record(dynamic, match[1].replace(/\.$/, ""), file);
  }
  for (const match of source.matchAll(/\bt\(\s*`([A-Za-z0-9_.@-]*?)\$\{/g)) {
    if (match[1]) record(dynamic, match[1].replace(/\.$/, ""), file);
  }
}

const problems = [];

for (const [key, files] of [...literal].sort()) {
  for (const [lang, catalog] of Object.entries(catalogs)) {
    if (!(key in catalog)) {
      problems.push(`missing in ${lang}: ${key} (${[...files].join(", ")})`);
    }
  }
}

for (const [prefix, files] of [...dynamic].sort()) {
  for (const [lang, catalog] of Object.entries(catalogs)) {
    // A namespace prefix must exist as an object in the catalog.
    const isNamespace = Object.keys(catalog).some((key) => key.startsWith(`${prefix}.`));
    if (!isNamespace) {
      problems.push(
        `dynamic key prefix is not a registered namespace in ${lang}: ${prefix}.* (${[...files].join(", ")})`,
      );
    }
  }
}

const zhKeys = new Set(Object.keys(catalogs.zh));
const enKeys = new Set(Object.keys(catalogs.en));
for (const key of zhKeys) {
  if (!enKeys.has(key)) problems.push(`catalog drift: ${key} is in zh but not en`);
}
for (const key of enKeys) {
  if (!zhKeys.has(key)) problems.push(`catalog drift: ${key} is in en but not zh`);
}

if (problems.length > 0) {
  console.error(`admin i18n key check FAILED (${problems.length} problem(s)):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}

console.log(
  `admin i18n key check OK (${literal.size} literal key(s), ${dynamic.size} dynamic prefix(es), ${zhKeys.size} key(s) per catalog)`,
);
