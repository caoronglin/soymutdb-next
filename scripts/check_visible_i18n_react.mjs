#!/usr/bin/env node
/**
 * Conservative visible-copy contract for active React/JSX portal sources.
 *
 * JSX text and user-facing static attributes must use the shared i18n catalogs.
 * Technical vocabulary is allowed by scripts/visible-i18n-allowlist.json. Counts
 * share scripts/visible-i18n-baseline.json with the legacy Vue scanner; each
 * scanner's baseline update preserves entries owned by the other file types.
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(SCRIPT_DIR, "..");
const SOURCE_ROOT = path.join(ROOT, "apps/web/src");
const BASELINE_PATH = path.join(SCRIPT_DIR, "visible-i18n-baseline.json");
const ALLOWLIST_PATH = path.join(SCRIPT_DIR, "visible-i18n-allowlist.json");
const ALLOWLIST = JSON.parse(fs.readFileSync(ALLOWLIST_PATH, "utf8"));
const ALLOWED_EXACT = new Set(ALLOWLIST.exact);
const ALLOWED_SHORT = new Set(ALLOWLIST.short);
const ALLOWED_PATTERNS = ALLOWLIST.patterns.map((pattern) => new RegExp(pattern));
const WORD_PATTERN = new RegExp(ALLOWLIST.wordPattern, "g");
const REACT_EXTENSIONS = new Set([".tsx", ".jsx"]);
const VISIBLE_ATTRIBUTES = new Set([
  "alt",
  "aria-description",
  "aria-label",
  "aria-placeholder",
  "aria-roledescription",
  "aria-valuetext",
  "cancelText",
  "caption",
  "children",
  "confirmText",
  "content",
  "description",
  "emptyText",
  "error",
  "help",
  "helperText",
  "label",
  "loadingText",
  "message",
  "okText",
  "placeholder",
  "prefix",
  "resetText",
  "submitText",
  "suffix",
  "text",
  "title",
  "tooltip",
]);
const TRANSLATION_FUNCTIONS = new Set(["t", "translate", "$t", "get"]);
const TRANSLATION_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_.:/-]*$/;
const NON_VISIBLE_STRING_METHODS = new Set([
  "endsWith",
  "includes",
  "indexOf",
  "join",
  "lastIndexOf",
  "match",
  "matchAll",
  "normalize",
  "padEnd",
  "padStart",
  "replace",
  "replaceAll",
  "search",
  "slice",
  "split",
  "startsWith",
  "substr",
  "substring",
  "test",
  "toLocaleString",
  "toLowerCase",
  "toUpperCase",
  "trim",
  "trimEnd",
  "trimStart",
]);

function isAllowed(text) {
  const words = text.match(WORD_PATTERN) ?? [];
  return words.every(
    (word) =>
      ALLOWED_EXACT.has(word) ||
      ALLOWED_SHORT.has(word) ||
      ALLOWED_PATTERNS.some((pattern) => pattern.test(word)),
  );
}

function isTranslationKey(node) {
  return (
    (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) &&
    TRANSLATION_KEY_PATTERN.test(node.text)
  );
}

function isTranslationCall(node) {
  // Static arguments must look like i18n keys, so unrelated get()/object.t()
  // calls cannot hide rendered prose. Dynamic t keys remain recognized so an
  // explicit defaultValue is still checked.
  if (!ts.isCallExpression(node) || !node.arguments[0]) return false;
  const expression = node.expression;
  const firstArgument = node.arguments[0];
  if (ts.isIdentifier(expression) && TRANSLATION_FUNCTIONS.has(expression.text)) {
    if (expression.text === "get") return isTranslationKey(firstArgument);
    return isTranslationKey(firstArgument) || !(ts.isStringLiteral(firstArgument) || ts.isNoSubstitutionTemplateLiteral(firstArgument));
  }
  if (ts.isPropertyAccessExpression(expression) && expression.name.text === "t") {
    return isTranslationKey(firstArgument) || !(ts.isStringLiteral(firstArgument) || ts.isNoSubstitutionTemplateLiteral(firstArgument));
  }
  return false;
}

function collectReturnStrings(node, output) {
  function visitReturns(current) {
    if (ts.isFunctionLike(current)) return;
    if (ts.isReturnStatement(current) && current.expression) {
      visibleStrings(current.expression, output);
      return;
    }
    ts.forEachChild(current, visitReturns);
  }

  visitReturns(node);
}

function visibleStrings(node, output) {
  if (ts.isJsxExpression(node) && node.expression) {
    visibleStrings(node.expression, output);
    return;
  }
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    output.push(node.text);
    return;
  }
  if (ts.isTemplateExpression(node)) {
    const fragments = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)];
    output.push(...fragments);
    for (const span of node.templateSpans) visibleStrings(span.expression, output);
    return;
  }
  if (isTranslationCall(node)) {
    // The first argument is a key, not user-facing copy. Inspect only explicit
    // defaultValue fallbacks in options, not arbitrary option/business strings.
    for (const argument of node.arguments.slice(1)) {
      if (ts.isObjectLiteralExpression(argument)) {
        for (const property of argument.properties) {
          const name = property.name && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
            ? property.name.text
            : "";
          if (name === "defaultValue" && ts.isPropertyAssignment(property)) {
            visibleStrings(property.initializer, output);
          }
        }
      } else {
        visibleStrings(argument, output);
      }
    }
    return;
  }
  if (ts.isCallExpression(node)) {
    const isMapCall = ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "map";
    if (isMapCall) {
      const callback = node.arguments[0];
      if (callback && (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) {
        if (ts.isBlock(callback.body)) {
          collectReturnStrings(callback.body, output);
        } else {
          visibleStrings(callback.body, output);
        }
      }
      return;
    }
    if (
      ts.isPropertyAccessExpression(node.expression) &&
      NON_VISIBLE_STRING_METHODS.has(node.expression.name.text)
    ) return;
    for (const argument of node.arguments) {
      if (!ts.isArrowFunction(argument) && !ts.isFunctionExpression(argument)) visibleStrings(argument, output);
    }
    return;
  }
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) return;
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isNonNullExpression(node)) {
    visibleStrings(node.expression, output);
    return;
  }
  if (ts.isConditionalExpression(node)) {
    visibleStrings(node.whenTrue, output);
    visibleStrings(node.whenFalse, output);
    return;
  }
  if (ts.isBinaryExpression(node)) {
    const visibleOperators = new Set([
      ts.SyntaxKind.AmpersandAmpersandToken,
      ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.QuestionQuestionToken,
      ts.SyntaxKind.PlusToken,
    ]);
    if (visibleOperators.has(node.operatorToken.kind)) {
      visibleStrings(node.left, output);
      visibleStrings(node.right, output);
    }
    return;
  }
  if (ts.isArrayLiteralExpression(node)) {
    for (const element of node.elements) visibleStrings(element, output);
  }
  // Do not recurse through arbitrary calls, object literals, or callback bodies:
  // they often contain comparison enums, CSS colors, and implementation labels.
}

function isVisibleInputValue(node, sourceFile) {
  if (!ts.isJsxAttribute(node) || node.name.getText(sourceFile) !== "value" || !ts.isJsxAttributes(node.parent)) {
    return false;
  }
  const opening = node.parent.parent;
  if (!ts.isJsxOpeningElement(opening) && !ts.isJsxSelfClosingElement(opening)) return false;
  if (opening.tagName.getText(sourceFile).toLowerCase() !== "input") return false;
  const typeAttribute = opening.attributes.properties.find(
    (attribute) => ts.isJsxAttribute(attribute) && attribute.name.getText(sourceFile) === "type",
  );
  return Boolean(
    typeAttribute &&
      ts.isJsxAttribute(typeAttribute) &&
      typeAttribute.initializer &&
      ts.isStringLiteral(typeAttribute.initializer) &&
      ["button", "submit", "reset"].includes(typeAttribute.initializer.text.toLowerCase()),
  );
}

function scanSource(fileName, source) {
  const extension = path.extname(fileName).toLowerCase();
  const scriptKind = extension === ".jsx" ? ts.ScriptKind.JSX : ts.ScriptKind.TSX;
  const sourceFile = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, scriptKind);
  const hits = [];

  function record(text, node) {
    const normalized = text
      .replace(/&(?:nbsp|thinsp|ensp|emsp|ldquo|rdquo|lsquo|rsquo|quot|apos|mdash|ndash|copy|reg|trade);/gi, " ")
      .replace(/&#(?:160|xA0);/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/\s+/g, " ")
      .trim();
    if (!normalized || !/[A-Za-z\u4e00-\u9fff]/.test(normalized) || isAllowed(normalized)) return;
    const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
    hits.push({ line, text: normalized });
  }

  function visit(node) {
    if (ts.isJsxText(node)) record(node.getText(sourceFile), node);
    if (ts.isJsxSpreadAttribute(node) && ts.isObjectLiteralExpression(node.expression)) {
      for (const property of node.expression.properties) {
        if (!ts.isPropertyAssignment(property)) continue;
        const name = property.name && (
          ts.isIdentifier(property.name) ||
          ts.isStringLiteral(property.name) ||
          ts.isNoSubstitutionTemplateLiteral(property.name)
        ) ? property.name.text : "";
        if (VISIBLE_ATTRIBUTES.has(name)) {
          const strings = [];
          visibleStrings(property.initializer, strings);
          for (const text of strings) record(text, property);
        }
      }
    }
    if (
      ts.isJsxAttribute(node) &&
      (VISIBLE_ATTRIBUTES.has(node.name.getText(sourceFile)) || isVisibleInputValue(node, sourceFile)) &&
      node.initializer
    ) {
      const strings = [];
      visibleStrings(node.initializer, strings);
      for (const text of strings) record(text, node);
    }
    if (
      ts.isJsxExpression(node) &&
      node.expression &&
      (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))
    ) {
      const strings = [];
      visibleStrings(node.expression, strings);
      for (const text of strings) record(text, node);
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return hits;
}

function isSourceFile(fileName) {
  const extension = path.extname(fileName).toLowerCase();
  const base = path.basename(fileName);
  return (
    REACT_EXTENSIONS.has(extension) &&
    !/\.(test|spec|stories)\.[jt]sx?$/i.test(base) &&
    !base.endsWith(".d.ts")
  );
}

function collect(root = ROOT) {
  const sourceRoot = path.join(root, "apps/web/src");
  const files = [];

  function walk(directory) {
    if (!fs.existsSync(directory)) return;
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.isDirectory()) {
        if (!["node_modules", "dist", "build", "__tests__"].includes(entry.name)) walk(path.join(directory, entry.name));
      } else if (entry.isFile() && isSourceFile(entry.name)) {
        files.push(path.join(directory, entry.name));
      }
    }
  }

  walk(sourceRoot);
  const hitsByFile = {};
  for (const file of files) {
    const hits = scanSource(file, fs.readFileSync(file, "utf8"));
    if (hits.length) hitsByFile[path.relative(root, file).split(path.sep).join("/")] = hits;
  }
  return hitsByFile;
}

function countsFor(hitsByFile) {
  return Object.fromEntries(Object.entries(hitsByFile).map(([file, hits]) => [file, hits.length]));
}

function normalizeCounts(counts, label) {
  if (!counts || typeof counts !== "object" || Array.isArray(counts)) {
    throw new Error(`${label} counts must be an object`);
  }
  for (const [file, count] of Object.entries(counts)) {
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) {
      throw new Error(`${label} count for ${file} must be a non-negative integer`);
    }
  }
  return counts;
}

function loadBaseline(fileName = BASELINE_PATH) {
  const data = JSON.parse(fs.readFileSync(fileName, "utf8"));
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`invalid baseline object: ${fileName}`);
  }
  const counts = Object.hasOwn(data, "counts") ? data.counts : data;
  return normalizeCounts(counts, `baseline ${fileName}`);
}

function mergeBaseline(previous, current) {
  const otherSources = Object.fromEntries(
    Object.entries(previous).filter(([file]) => !REACT_EXTENSIONS.has(path.extname(file).toLowerCase())),
  );
  return { ...otherSources, ...current };
}

function check(counts, baseline) {
  const validBaseline = normalizeCounts(baseline, "baseline");
  return Object.entries(counts)
    .filter(([file, count]) => count > (validBaseline[file] ?? 0))
    .map(([file, count]) => `${file}: ${count} hardcoded string(s), baseline ${validBaseline[file] ?? 0}`);
}

function writeBaseline(fileName, counts) {
  const previous = fs.existsSync(fileName) ? loadBaseline(fileName) : {};
  const payload = {
    comment: "Hardcoded visible strings per Vue/React source file. Counts may fall but must never rise; remove an entry once the page is translated.",
    counts: mergeBaseline(previous, counts),
  };
  fs.writeFileSync(fileName, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function selfTest() {
  const fixture = `
    export function Demo({ ready }) {
      return <>
        <div className={ready ? "text-primary" : "text-muted-foreground"} />
        <h1>Translate this heading</h1>
        <input placeholder="Search genes" aria-label={t("search.label")} />
        <Select value={ready ? "all" : "none"} />
        <input value="Glyma.01G000100" />
        <input type="submit" value="Send request" />
        <img alt="Glyma.01G000100" />
        <span>Glyma.01G000100 · SNP · HIGH · EMS · RNA-Seq</span>
        <Notice children="No results found" />
        <Panel {...{ title: "Help panel" }} />
        <Empty description="No matching variants" />
        <Alert message="Upload failed" />
        <button aria-label={t("button.save")}>Save</button>
        <p>{t("compare.title")}</p>
        <p>{get("common.save", t("common.save"))}</p>
        <p>{fallback("Open reference")}</p>
        <p>{ready ? "Loading records" : null}</p>
        <p>{t("empty", { defaultValue: "No data available" })}</p>
        <p>{get("empty.key", "Open results")}</p>
        <p>{get("Visible fallback copy")}</p>
        <p>{metadata.t("Secondary help text")}</p>
        <p>{t("Unlocalized title")}</p>
        <p>{get(group.labelKey, t(group.labelKey, { defaultValue: "Missing label" }))}</p>
        <p>{chromosome.replace("chr", "")}</p>
        <p>{items.map((item) => { const kind = "cen"; const fill = "oklch(0.3 0.05 150)"; return <span aria-label={"Open " + item.name + " band"} />; })}</p>
        <p>{items.map((item) => { if (!item) return "No records"; const status = "hidden"; return null; })}</p>
        <span>&nbsp; &ldquo;Quoted interface text&rdquo;</span>
      </>
    }`;
  const hits = scanSource("Demo.tsx", fixture);
  const texts = hits.map((hit) => hit.text);
  const expected = [
    "Translate this heading",
    "Search genes",
    "Send request",
    "No results found",
    "Help panel",
    "No matching variants",
    "Upload failed",
    "Save",
    "Open reference",
    "Loading records",
    "No data available",
    "Open results",
    "Visible fallback copy",
    "Secondary help text",
    "Unlocalized title",
    "Missing label",
    "Open",
    "band",
    "No records",
    "Quoted interface text",
  ];
  if (JSON.stringify(texts) !== JSON.stringify(expected)) {
    throw new Error(`JSX extraction mismatch: ${JSON.stringify(texts)}`);
  }
  if (check({ "apps/web/src/routes/Demo.tsx": 1 }, {})[0] !== "apps/web/src/routes/Demo.tsx: 1 hardcoded string(s), baseline 0") {
    throw new Error("baseline check did not fail on a new visible string");
  }
  for (const malformed of ["oops", -1, 1.5, Number.NaN]) {
    let rejected = false;
    try {
      check({}, { "apps/web/src/routes/Demo.tsx": malformed });
    } catch {
      rejected = true;
    }
    if (!rejected) throw new Error(`malformed baseline count was accepted: ${String(malformed)}`);
  }
  const merged = mergeBaseline(
    { "apps/admin/src/views/Legacy.vue": 6, "apps/web/src/routes/Old.tsx": 3 },
    { "apps/web/src/routes/Compare.tsx": 2 },
  );
  if (JSON.stringify(merged) !== JSON.stringify({
    "apps/admin/src/views/Legacy.vue": 6,
    "apps/web/src/routes/Compare.tsx": 2,
  })) {
    throw new Error(`baseline merge mismatch: ${JSON.stringify(merged)}`);
  }
  console.log("React visible i18n self-test passed");
  return 0;
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes("--self-test")) return selfTest();
  const update = args.includes("--update-baseline");
  const baselineOption = args.indexOf("--baseline");
  const baselinePath = baselineOption >= 0 ? path.resolve(args[baselineOption + 1]) : BASELINE_PATH;
  const hitsByFile = collect();
  const counts = countsFor(hitsByFile);

  if (update) {
    writeBaseline(baselinePath, counts);
    console.log(`React baseline written: ${Object.keys(counts).length} file(s), ${Object.values(counts).reduce((sum, value) => sum + value, 0)} string(s)`);
    return 0;
  }
  if (!fs.existsSync(baselinePath)) {
    console.error(`missing baseline: ${baselinePath}`);
    return 1;
  }

  const failures = check(counts, loadBaseline(baselinePath));
  if (failures.length) {
    for (const failure of failures) {
      console.error(`FAIL: ${failure}`);
      for (const hit of hitsByFile[failure.split(":", 1)[0]] ?? []) {
        console.error(`  L${hit.line}: ${JSON.stringify(hit.text)}`);
      }
    }
    console.error("Move UI copy into the en/zh locale catalogs or document a canonical token in the shared allowlist.");
    return 1;
  }

  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  console.log(`React visible i18n OK (${total} tracked string(s) in ${Object.keys(counts).length} file(s))`);
  return 0;
}

process.exitCode = main();
