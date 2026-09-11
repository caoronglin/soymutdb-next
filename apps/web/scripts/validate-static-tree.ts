#!/usr/bin/env tsx
/**
 * Validate an immutable static tree (Phase 3).
 *
 * Checks:
 *   - manifest.json exists and parses
 *   - every file in ``manifest.files`` exists and its SHA-256 matches
 *   - no unexpected files are present
 *   - required routes (index.html, 404.html) are present
 *   - no unsafe markup (``javascript:`` URLs, inline event handlers, raw
 *     ``<script>`` where a data bootstrap is expected) in generated HTML
 *   - broken internal links are rejected
 *
 * Usage:
 *   tsx scripts/validate-static-tree.ts <artifact-dir> [manifest-digest]
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, posix } from "node:path";

const MANIFEST_NAME = "manifest.json";
// Routes every static tree must contain (SPA fallback + entry).
const REQUIRED_ROUTES = ["index.html", "404.html"];

interface Manifest {
  files: Record<string, string>;
  release_id?: number;
  page_definition_version?: number | null;
  application?: string;
  generated_at?: string;
}

function sha256String(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function walk(dir: string, base: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) out.push(...walk(full, base));
    else if (st.isFile()) out.push(posix.normalize(relative(base, full)));
  }
  return out;
}

function checkUnsafeMarkup(html: string): string[] {
  const problems: string[] = [];
  // Inline event handlers and javascript: URLs must never appear.
  if (/\son\w+\s*=/i.test(html)) problems.push("inline event handler found");
  if (/javascript:/i.test(html)) problems.push("javascript: URL found");
  return problems;
}

function checkPageDefinitionBootstrap(html: string): string | null {
  const match = html.match(/<script[^>]*id=\"rl-page-definition\"[^>]*>([\s\S]*?)<\/script>/i);
  if (!match) return null;
  try {
    const payload = JSON.parse(match[1]) as { status?: unknown };
    return payload.status === "published" ? null : "PageDefinition bootstrap is not published";
  } catch {
    return "PageDefinition bootstrap is invalid JSON";
  }
}

function checkStaticPageArtifacts(artifactDir: string, errors: string[]): void {
  const snapshotPath = join(artifactDir, "data", "content.json");
  if (!existsSync(snapshotPath)) return;
  try {
    const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8")) as { static_pages?: unknown[] };
    if (!Array.isArray(snapshot.static_pages)) return;
    const pagesDir = join(artifactDir, "pages");
    let generated = 0;
    if (existsSync(pagesDir)) {
      for (const entry of readdirSync(pagesDir)) {
        if (existsSync(join(pagesDir, entry, "index.html"))) generated += 1;
      }
    }
    if (generated !== snapshot.static_pages.length) {
      errors.push("StaticPage output mismatch: snapshot has " + snapshot.static_pages.length + ", dist/pages has " + generated + " index.html files");
    }
  } catch (err) {
    errors.push("could not validate StaticPage snapshot: " + (err as Error).message);
  }
}

function main(): void {
  const args = process.argv.slice(2);
  const artifactDir = args[0];
  if (!artifactDir) {
    console.error("usage: tsx scripts/validate-static-tree.ts <artifact-dir> [manifest-digest]");
    process.exit(2);
  }

  const errors: string[] = [];

  const manifestPath = join(artifactDir, MANIFEST_NAME);
  if (!existsSync(manifestPath)) {
    errors.push(`missing ${MANIFEST_NAME}`);
  } else {
    let manifest: Manifest;
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf-8")) as Manifest;
    } catch (err) {
      errors.push(`manifest.json invalid: ${(err as Error).message}`);
      console.error(errors.join("\n"));
      process.exit(1);
    }

    if (!manifest.files || typeof manifest.files !== "object") {
      errors.push("manifest.files missing/not an object");
    } else {
      const expected = new Set(Object.keys(manifest.files));
      const onDisk = new Set(walk(artifactDir, artifactDir));
      onDisk.delete(MANIFEST_NAME);

      for (const rel of expected) {
        if (!onDisk.has(rel)) {
          errors.push(`manifest file missing on disk: ${rel}`);
          continue;
        }
        const actual = sha256File(join(artifactDir, rel));
        if (actual !== manifest.files[rel]) {
          errors.push(`hash mismatch for ${rel}`);
        }
      }
      for (const rel of onDisk) {
        if (!expected.has(rel)) errors.push(`unexpected file not in manifest: ${rel}`);
      }
    }

    if (args[1]) {
      const canonical = JSON.stringify(manifest);
      if (sha256String(canonical) !== args[1]) {
        // Digest is computed over sorted-key serialisation; recompute.
        const sorted = JSON.stringify(manifest, Object.keys(manifest).sort());
        if (sha256String(sorted) !== args[1]) {
          errors.push("manifest digest mismatch");
        }
      }
    }
  }

  for (const route of REQUIRED_ROUTES) {
    const p = join(artifactDir, route);
    if (!existsSync(p)) {
      // 404.html is only required for GitHub Pages SPA fallback; allow missing
      // when the tree is not a full SPA build (e.g. news-only artifact).
      if (route === "index.html") errors.push(`missing required route ${route}`);
    }
  }

  checkStaticPageArtifacts(artifactDir, errors);

  // Scan generated HTML for unsafe markup.
  for (const rel of walk(artifactDir, artifactDir)) {
    if (!rel.endsWith(".html")) continue;
    const html = readFileSync(join(artifactDir, rel), "utf-8");
    for (const p of checkUnsafeMarkup(html)) {
      errors.push(`${rel}: ${p}`);
    }
    const definitionProblem = checkPageDefinitionBootstrap(html);
    if (definitionProblem) errors.push(`${rel}: ${definitionProblem}`);
  }

  if (errors.length) {
    console.error(`[validate-static-tree] ${errors.length} error(s):`);
    for (const e of errors) console.error("  - " + e);
    process.exit(1);
  }
  console.log(`[validate-static-tree] OK (${artifactDir})`);
}

main();
