#!/usr/bin/env node
/**
 * Verify that English and Chinese common locale JSON files expose identical
 * nested keys. Values may differ; missing keys and shape mismatches fail.
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(fileURLToPath(import.meta.url));
const DEFAULT_EN = join(packageRoot, "src/locales/en/common.json");
const DEFAULT_ZH = join(packageRoot, "src/locales/zh/common.json");

function flatten(value, prefix = "", output = new Map()) {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    for (const key of Object.keys(value).sort()) {
      flatten(value[key], prefix ? prefix + "." + key : key, output);
    }
    return output;
  }
  output.set(prefix, Array.isArray(value) ? "array" : typeof value);
  return output;
}

export function checkLocaleKeys(enPath, zhPath) {
  const en = flatten(JSON.parse(readFileSync(enPath, "utf8")));
  const zh = flatten(JSON.parse(readFileSync(zhPath, "utf8")));
  const missingZh = [...en.keys()].filter((key) => !zh.has(key)).sort();
  const missingEn = [...zh.keys()].filter((key) => !en.has(key)).sort();
  const shapeMismatch = [...en.keys()]
    .filter((key) => zh.has(key) && en.get(key) !== zh.get(key))
    .sort();
  return { missingZh, missingEn, shapeMismatch };
}

function printResult(result) {
  const problems = [
    ...result.missingZh.map((key) => "missing zh key: " + key),
    ...result.missingEn.map((key) => "missing en key: " + key),
    ...result.shapeMismatch.map((key) => "value shape mismatch: " + key),
  ];
  if (problems.length) {
    console.error("Locale key check failed:");
    for (const problem of problems) console.error(" - " + problem);
    return false;
  }
  console.log("Locale key check passed");
  return true;
}

function selfTest() {
  const dir = mkdtempSync(join(tmpdir(), "soymutdb-i18n-"));
  try {
    const en = join(dir, "en.json");
    const zh = join(dir, "zh.json");
    writeFileSync(en, JSON.stringify({ nav: { home: "Home" }, count: 1 }));
    writeFileSync(zh, JSON.stringify({ nav: { home: "首页" }, count: 2 }));
    if (!printResult(checkLocaleKeys(en, zh))) throw new Error("equal key fixture failed");
    writeFileSync(zh, JSON.stringify({ nav: { extra: "额外" }, count: [] }));
    const invalid = checkLocaleKeys(en, zh);
    if (!invalid.missingZh.includes("nav.home") || !invalid.missingEn.includes("nav.extra") || !invalid.shapeMismatch.includes("count")) {
      throw new Error("mismatch fixture failed");
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  console.log("Locale key checker self-test passed");
}

const args = process.argv.slice(2);
if (args[0] === "--self-test") {
  selfTest();
} else {
  const [enPath = DEFAULT_EN, zhPath = DEFAULT_ZH] = args;
  if (!printResult(checkLocaleKeys(enPath, zhPath))) process.exitCode = 1;
}
