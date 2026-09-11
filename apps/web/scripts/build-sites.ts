#!/usr/bin/env tsx
/**
 * Build both explicitly selected SoyMutDB site artifacts.
 *
 * This is intentionally a sequential orchestrator: external and internal are
 * independent static trees under dist/external and dist/internal, and every
 * post-build step receives the same explicit variant and output directory.
 * There is no hostname, cookie, IP, or request-time site detection.
 */

import { spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.cwd();
const BIN_DIR = join(ROOT, "node_modules", ".bin");
const BIN_SUFFIX = process.platform === "win32" ? ".cmd" : "";
const VARIANTS = ["external", "internal"] as const;
type SiteVariant = (typeof VARIANTS)[number];

function isProduction(): boolean {
  const mode = process.env.VITE_DEPLOYMENT_MODE?.trim().toLowerCase();
  return mode === "production" || process.env.CI === "true";
}

function siteUrlFor(variant: SiteVariant): string {
  const configured = variant === "internal"
    ? process.env.SOYMUTDB_INTERNAL_SITE_URL?.trim()
    : process.env.SOYMUTDB_SITE_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");
  if (isProduction()) {
    throw new Error(
      variant === "internal"
        ? "SOYMUTDB_INTERNAL_SITE_URL is required for an internal production artifact"
        : "SOYMUTDB_SITE_URL is required for a production artifact",
    );
  }
  return variant === "internal"
    ? "https://internal.soymutdb.invalid"
    : "https://soymutdb.org";
}

function run(command: string, args: string[], env: NodeJS.ProcessEnv): void {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(command + " " + args.join(" ") + " exited with status " + (result.status ?? "unknown"));
  }
}

function buildVariant(variant: SiteVariant): void {
  const relativeDist = join("dist", variant);
  const distDir = join(ROOT, relativeDist);
  if (existsSync(distDir)) rmSync(distDir, { recursive: true, force: true });

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    VITE_SITE_VARIANT: variant,
    VITE_SOYMUTDB_RELEASE_ID: process.env.SOYMUTDB_RELEASE_ID,
    SOYMUTDB_SITE_VARIANT: variant,
    SOYMUTDB_DIST_DIR: relativeDist,
    SOYMUTDB_SITE_URL: siteUrlFor(variant),
  };

  console.log("[build:sites] Building " + variant + " -> " + distDir);
  const vite = join(BIN_DIR, "vite" + BIN_SUFFIX);
  const tsx = join(BIN_DIR, "tsx" + BIN_SUFFIX);
  run(vite, ["build", "--outDir", relativeDist], env);
  run(tsx, ["scripts/ssg-build.ts"], env);
  run(tsx, ["scripts/generate-samples.ts"], env);
  run(tsx, ["scripts/fetch-content-snapshot.ts"], env);
  run(tsx, ["scripts/ssg-content.ts"], env);
  run(tsx, ["scripts/embed-page-definitions.ts"], env);
  run(tsx, ["scripts/gzip-compress.ts"], env);
  run(process.execPath, ["scripts/gen-sw.js"], env);
  run(tsx, ["scripts/release-manifest.ts"], env);
}

for (const variant of VARIANTS) buildVariant(variant);
console.log("[build:sites] External and internal artifacts are ready.");
