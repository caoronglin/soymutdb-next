#!/usr/bin/env node
/**
 * Behaviour tests for `check_visible_i18n_react.mjs`.
 *
 * The guard is the only thing standing between the portal and English-only
 * copy, so "it passes" is not evidence — what matters is that it still fails
 * on real hardcoded text after any narrowing.
 *
 * The narrowing this file locks down: a template literal passed as a function
 * argument is a composite programmatic string (a React key prefix, a selector),
 * not user-facing copy. Before the change, `renderInline(text, `bq-${key}`)`
 * in the usage guide was reported as four hardcoded strings, and the only way
 * to silence it was to put a React key in the translation catalog.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const GUARD = path.join(ROOT, "scripts", "check_visible_i18n_react.mjs");

/** Run the guard over a synthetic source tree and return its stdout/stderr. */
function run(files) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "i18n-guard-"));
  try {
    const src = path.join(tmp, "apps", "web", "src", "components");
    fs.mkdirSync(src, { recursive: true });
    for (const [name, body] of Object.entries(files)) {
      fs.writeFileSync(path.join(src, name), body, "utf8");
    }
    try {
      const stdout = execFileSync("node", [GUARD, "--root", tmp], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      });
      return { code: 0, stdout };
    } catch (error) {
      return { code: error.status ?? 1, stdout: error.stdout ?? "", stderr: error.stderr ?? "" };
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, error: error.message });
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

check("a hardcoded JSX string is still reported", () => {
  const out = run({ "page.tsx": `export default function P() {\n  return <p>Hello world</p>;\n}\n` });
  assert(out.code === 1, `expected exit 1, got ${out.code}`);
  assert(out.stderr.includes("Hello world"), `expected the literal to be named, got: ${out.stderr}`);
});

check("a hardcoded visible attribute is still reported", () => {
  const out = run({ "page.tsx": `export default function P() {\n  return <img src="a.png" alt="A chart" />;\n}\n` });
  assert(out.code === 1, `expected exit 1, got ${out.code}`);
  assert(out.stderr.includes("A chart"), `expected alt copy to be named, got: ${out.stderr}`);
});

check("a translated string with an inline defaultValue is still reported", () => {
  const out = run({
    "page.tsx": `import { useTranslation } from "react-i18next";\n` +
      `export default function P() {\n  const { t } = useTranslation();\n` +
      `  return <p>{t("nav.home", { defaultValue: "Home" })}</p>;\n}\n`,
  });
  assert(out.code === 1, `expected exit 1, got ${out.code}`);
  assert(out.stderr.includes("Home"), `expected the defaultValue copy to be named, got: ${out.stderr}`);
});

check("a literal fallback argument is still reported", () => {
  const out = run({ "page.tsx": `export default function P() {\n  return <p>{get("a.b", "Fallback text")}</p>;\n}\n` });
  assert(out.code === 1, `expected exit 1, got ${out.code}`);
  assert(out.stderr.includes("Fallback text"), `expected the fallback to be named, got: ${out.stderr}`);
});

check("a React key prefix passed as a template argument is not copy", () => {
  const out = run({
    // Mirrors apps/web/src/routes/guide.tsx: the text is split and joined, so
    // the only literal in the call is the key prefix.
    "page.tsx": `function renderInline(text: string, keyPrefix: string) { return [text]; }\n` +
      `export default function P() {\n` +
      `  const key = 1;\n` +
      '  return <ul>{renderInline(["body"].join(" "), `bq-${key}`)}</ul>;\n}\n',
  });
  assert(out.code === 0, `expected exit 0 for a key prefix, got ${out.code}: ${out.stderr}`);
});

check("a hardcoded alt spread across lines is still reported", () => {
  // The 2026-10-02 audit recorded that a line-oriented <img> scan missed a
  // multi-line alt. The guard is AST-based; this pins that the multi-line
  // shape is still caught, because the fix must not regress to line matching.
  const out = run({
    "card.tsx": `export default function Card() {
  return (
    <img
      src="/a.png"
      alt="A descriptive alternative text
           that wraps across lines"
    />
  );
}
`,
  });
  assert(out.code === 1, `expected exit 1 for a multi-line alt, got ${out.code}`);
  assert(out.stderr.includes("alternative text"), `expected the alt copy to be named, got: ${out.stderr}`);
});

check("a dynamic alt expression is not reported as copy", () => {
  // `alt={item.cover_alt_text ?? title}` is data, not copy; flagging it would
  // push the developer to invent a translation key for user content.
  const out = run({
    "card.tsx": `export default function Card({ item, title }: { item: { alt: string }; title: string }) {
  return <img src="/a.png" alt={item.alt ?? title} />;
}
`,
  });
  assert(out.code === 0, `expected exit 0 for a dynamic alt, got ${out.code}: ${out.stderr}`);
});

check("a template rendered as visible JSX text is still copy", () => {
  const out = run({
    "page.tsx": `export default function P({ n }: { n: number }) {\n` +
      '  return <p>Showing ${n} rows</p>;\n}\n',
  });
  assert(out.code === 1, `expected exit 1 for a visible template, got ${out.code}`);
  assert(out.stderr.includes("Showing"), `expected the visible template to be named, got: ${out.stderr}`);
});

check("Chinese copy in a JSX child is reported", () => {
  // Regression: the allowlist pattern `^[\\W\\d_]+$` classified every CJK
  // code point as a non-word character, so a pure-Chinese string matched the
  // "punctuation and digits only" exemption and was never reported. Half the
  // portal's copy is Chinese; the guard was silent on all of it.
  const out = run({ "page.tsx": `export default function P() {\n  return <p>\u57fa\u56e0\u7ec4\u89c6\u56fe</p>;\n}\n` });
  assert(out.code === 1, `expected exit 1 for Chinese JSX text, got ${out.code}`);
  assert(out.stderr.includes("\u57fa\u56e0\u7ec4\u89c6\u56fe"), `expected the Chinese literal to be named, got: ${out.stderr}`);
});

check("Chinese copy in a visible attribute is reported", () => {
  const out = run({ "page.tsx": `export default function P() {\n  return <Button aria-label="\u5de6\u79fb" />;\n}\n` });
  assert(out.code === 1, `expected exit 1 for a Chinese aria-label, got ${out.code}`);
  assert(out.stderr.includes("\u5de6\u79fb"), `expected the Chinese label to be named, got: ${out.stderr}`);
});

check("a Chinese defaultValue in a visible position is reported like an English one", () => {
  // The guard already inspects `defaultValue` fallbacks. The CJK exemption made
  // the same shape pass in Chinese and fail in English, which is the bug.
  const zh = run({
    "page.tsx": `export default function P() {\n  return <p>{t("a.b", { defaultValue: "\u57fa\u56e0\u7ec4\u89c6\u56fe" })}</p>;\n}\n`,
  });
  const en = run({
    "page.tsx": `export default function P() {\n  return <p>{t("a.b", { defaultValue: "Genome view" })}</p>;\n}\n`,
  });
  assert(en.code === 1, `expected the English defaultValue to be reported, got ${en.code}`);
  assert(zh.code === 1, `expected the Chinese defaultValue to be reported too, got ${zh.code}`);
  assert(zh.stderr.includes("\u57fa\u56e0\u7ec4\u89c6\u56fe"), `expected the Chinese fallback to be named, got: ${zh.stderr}`);
});

check("punctuation and digit-only strings are still exempt", () => {
  // The exemption exists for separators and counts, not for prose. Widening it
  // is what hid the Chinese copy, so pin that the original purpose still holds.
  const out = run({
    "sep.tsx": `export default function Sep() {\n  return <p>\u2014 \u00b7 \u00d7 \u2192</p>;\n}\n` +
      `export function Count() {\n  return <span>1,234</span>;\n}\n`,
  });
  assert(out.code === 0, `expected exit 0 for separators and digits, got ${out.code}: ${out.stderr}`);
});

check("a mixed Chinese and English string is reported", () => {
  const out = run({ "page.tsx": `export default function P() {\n  return <p>\u5df2\u53d1\u5e03 published rows</p>;\n}\n` });
  assert(out.code === 1, `expected exit 1 for mixed copy, got ${out.code}`);
});

let failed = 0;
for (const result of results) {
  if (result.ok) {
    console.log(`ok - ${result.name}`);
  } else {
    failed += 1;
    console.error(`not ok - ${result.name}\n    ${result.error}`);
  }
}
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);