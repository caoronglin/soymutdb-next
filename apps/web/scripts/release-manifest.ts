#!/usr/bin/env tsx
/**
 * Release manifest + integrity digest writer for the production build path.
 *
 * In strict production mode (`VITE_DEPLOYMENT_MODE=production`) the build MUST
 * bind a real release id and emit a deterministic `manifest.json` plus a
 * `SHA256SUMS` file over the final static tree. Both are consumed by the
 * deploy pipeline / evidence archive to prove the exact artifact that was
 * published.
 *
 * When run as a CLI at the end of `apps/web` build, this step is a no-op for
 * Demo / Standard / Minimal builds (they are non-release artifacts) and a hard
 * gate for Production (it throws when `SOYMUTDB_RELEASE_ID` is missing).
 *
 * Usage (as CLI):  tsx scripts/release-manifest.ts
 */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, posix, relative } from "node:path";
import { isProductionDeploymentMode } from "../src/lib/deployment";

const MANIFEST_NAME = "manifest.json";
const SHA256_NAME = "SHA256SUMS";
const DIST_DIR = join(process.cwd(), "dist");

/** A real positive release id is mandatory for a production artifact. */
export function requireReleaseId(env: NodeJS.ProcessEnv): number {
  const raw = env.SOYMUTDB_RELEASE_ID?.trim();
  if (!raw) {
    throw new Error(
      "Production build requires SOYMUTDB_RELEASE_ID (a real release_id) — refusing to emit an untagged artifact",
    );
  }
  const id = Number(raw);
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new Error(`SOYMUTDB_RELEASE_ID must be a positive integer: ${raw}`);
  }
  return id;
}

/** SHA-256 hex digest of a single file. */
export function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

/** Recursively collect all files under `dir`. */
function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) out.push(...walk(full));
    else if (stat.isFile()) out.push(full);
  }
  return out;
}

/**
 * Walk the built static tree and write `manifest.json` (per-file SHA-256 +
 * release metadata) and `SHA256SUMS`. Deterministic: files are sorted and the
 * digest lines fixed-format so re-running produces identical output.
 *
 * Returns the counts/paths for reporting.
 */
export function writeReleaseManifest(
  distDir: string,
  releaseId: number,
  application = "soymutdb-next",
): { fileCount: number; manifestPath: string; sha256Path: string } {
  const files: Record<string, string> = {};
  for (const file of walk(distDir).sort()) {
    const rel = posix.normalize(relative(distDir, file));
    if (rel === MANIFEST_NAME || rel === SHA256_NAME) continue;
    files[rel] = sha256File(file);
  }

  const manifest = {
    schema_version: 1,
    release_id: releaseId,
    application,
    generated_at: new Date().toISOString(),
    files,
  };
  const manifestPath = join(distDir, MANIFEST_NAME);
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");

  const lines = Object.entries(files)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([rel, hash]) => `${hash}  ${rel}`)
    .join("\n");
  const sha256Path = join(distDir, SHA256_NAME);
  writeFileSync(sha256Path, `${lines}\n`, "utf8");

  return {
    fileCount: Object.keys(files).length,
    manifestPath,
    sha256Path,
  };
}

function main(): void {
  const production = isProductionDeploymentMode(process.env.VITE_DEPLOYMENT_MODE);
  if (!production) {
    console.log(
      `[release-manifest] Non-production build (mode=${process.env.VITE_DEPLOYMENT_MODE ?? "standard"}) — skipped (Demo/Standard/Minimal do not emit a release manifest).`,
    );
    process.exit(0);
  }

  const releaseId = requireReleaseId(process.env);
  const { fileCount, manifestPath, sha256Path } = writeReleaseManifest(DIST_DIR, releaseId);
  console.log(
    `[release-manifest] Production manifest written: ${manifestPath} + ${sha256Path} (${fileCount} files, release_id=${releaseId})`,
  );
}

// Only auto-run when invoked as the build-script CLI (import.meta.url is the
// module entry); when imported by a test it must not run main().
if (process.argv[1] === import.meta.filename) {
  main();
}
