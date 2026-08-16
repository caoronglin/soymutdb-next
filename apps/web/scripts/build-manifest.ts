#!/usr/bin/env tsx
/**
 * Build a release manifest for an immutable static tree (Phase 3).
 *
 * Walks ``dist/releases/<release-id>/<digest>/`` (or a path/args) and writes
 * ``manifest.json`` containing every relative file path and its SHA-256,
 * plus release / page-definition / application metadata.  Deterministic:
 * files are sorted and the JSON is serialised with sorted keys.
 *
 * Usage:
 *   tsx scripts/build-manifest.ts <artifact-dir> <release-id> [page-def-version]
 */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, posix } from "node:path";

const MANIFEST_NAME = "manifest.json";

function sha256File(path: string): string {
  const data = readFileSync(path);
  return createHash("sha256").update(data).digest("hex");
}

function walk(dir: string, base: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      out.push(...walk(full, base));
    } else if (st.isFile()) {
      out.push(posix.normalize(relative(base, full)));
    }
  }
  return out;
}

function main(): void {
  const args = process.argv.slice(2);
  const artifactDir = args[0];
  const releaseId = Number(args[1]);
  const pageDefVersion = args[2] ? Number(args[2]) : undefined;
  if (!artifactDir || Number.isNaN(releaseId)) {
    console.error(
      "usage: tsx scripts/build-manifest.ts <artifact-dir> <release-id> [page-def-version]",
    );
    process.exit(2);
  }

  const files: Record<string, string> = {};
  for (const rel of walk(artifactDir, artifactDir).sort()) {
    if (rel === MANIFEST_NAME) continue;
    files[rel] = sha256File(join(artifactDir, rel));
  }

  const manifest = {
    schema_version: 1,
    release_id: releaseId,
    page_definition_version: pageDefVersion ?? null,
    application: "soymutdb-next",
    generated_at: new Date().toISOString(),
    files,
  };

  const out = join(artifactDir, MANIFEST_NAME);
  writeFileSync(out, JSON.stringify(manifest, null, 2) + "\n", "utf-8");
  const digest = createHash("sha256")
    .update(JSON.stringify(manifest, Object.keys(manifest).sort()))
    .digest("hex");
  console.log(`[build-manifest] wrote ${out} (${Object.keys(files).length} files, digest ${digest})`);
}

main();
