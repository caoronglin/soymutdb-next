#!/usr/bin/env node
/**
 * Ant Design source scan (`antd lint`) as a hard frontend gate.
 *
 * `@ant-design/cli` exits 0 even when it reports findings, so running it from a
 * shell step cannot fail the pipeline. This wrapper asks for `--format json`,
 * checks every target, and exits non-zero when any issue is reported. It runs
 * the same binary the workspace pins through the pnpm catalog.
 *
 * Blind spot: the CLI resolves literal `antd` imports. This repository imports
 * through the `@/lib/antd` facade, so prop-level findings inside components can
 * be invisible here. Facade export completeness is covered separately by
 * `apps/admin/src/regression/antd-facade-exports.test.ts`; the CLI's own
 * `usage` command has the same limitation and is deliberately not used.
 *
 * Usage: node scripts/check-antd-design.mjs [--self-test]
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CLI_ENTRY = path.join(ROOT, "node_modules", "@ant-design", "cli", "dist", "index.js");
const TARGETS = ["apps/web/src", "apps/admin/src"];
const SELF_TEST = process.argv.includes("--self-test");

function runLint(target, home) {
  const result = spawnSync(
    process.execPath,
    [CLI_ENTRY, "--format", "json", "lint", target],
    {
      cwd: ROOT,
      encoding: "utf8",
      timeout: 300_000,
      env: {
        ...process.env,
        HOME: home,
        XDG_CACHE_HOME: path.join(home, ".cache"),
        CI: "1",
      },
    },
  );

  if (result.error) {
    throw new Error(`antd lint could not start for ${target}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(
      `antd lint failed for ${target} (exit ${result.status}):\n${result.stderr || result.stdout}`,
    );
  }

  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    throw new Error(
      `antd lint returned non-JSON output for ${target}:\n${result.stdout}\n${result.stderr}`,
    );
  }
  if (report.partial === true) {
    throw new Error(
      `antd lint reported a partial scan for ${target}; a partial scan is not a pass`,
    );
  }
  return report;
}

function printIssues(target, report) {
  for (const issue of report.issues ?? []) {
    const location = path.relative(ROOT, issue.file) || issue.file;
    console.error(
      `  ${location}:${issue.line ?? "?"} [${issue.rule}] ${issue.message}`,
    );
  }
  const summary = report.summary ?? {};
  console.error(
    `  ${target}: ${summary.deprecated ?? 0} deprecated, ${summary.a11y ?? 0} a11y, ` +
      `${summary.usage ?? 0} usage, ${summary.performance ?? 0} performance`,
  );
}

function scan(targets, home, { quiet = false } = {}) {
  let failed = 0;
  for (const target of targets) {
    const report = runLint(target, home);
    const issueCount = (report.issues ?? []).length;
    if (issueCount > 0) {
      failed += 1;
      printIssues(target, report);
    } else if (!quiet) {
      console.log(`  ${target}: no issues (${report.summary?.total ?? 0} findings)`);
    }
  }
  return failed;
}

function selfTest(home) {
  const fixtureRoot = mkdtempSync(path.join(tmpdir(), "soymutdb-antd-scan-"));
  try {
    const clean = path.join(fixtureRoot, "clean");
    const dirty = path.join(fixtureRoot, "dirty");
    mkdirSync(clean);
    mkdirSync(dirty);
    writeFileSync(
      path.join(clean, "clean.tsx"),
      'import { Card } from "antd";\nexport const Clean = () => <Card />;\n',
    );
    writeFileSync(
      path.join(dirty, "dirty.tsx"),
      'import { Card } from "antd";\nexport const Dirty = () => <Card bodyStyle={{ padding: 1 }} />;\n',
    );

    const cleanReport = runLint(clean, home);
    if ((cleanReport.issues ?? []).length !== 0) {
      throw new Error("self-test: a clean component must produce no findings");
    }

    const dirtyReport = runLint(dirty, home);
    if ((dirtyReport.issues ?? []).length === 0) {
      throw new Error(
        "self-test: the deprecated prop fixture produced no findings; the scan is not reading the target",
      );
    }
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
}

let home;
try {
  home = mkdtempSync(path.join(tmpdir(), "soymutdb-antd-home-"));
  if (SELF_TEST) {
    console.log("antd design scan self-test");
    selfTest(home);
    console.log("  self-test passed");
  }
  const failed = scan(TARGETS, home);
  if (failed > 0) {
    console.error(`antd design scan FAILED for ${failed} target(s)`);
    process.exit(1);
  }
  console.log("antd design scan passed");
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(2);
} finally {
  if (home) rmSync(home, { recursive: true, force: true });
}