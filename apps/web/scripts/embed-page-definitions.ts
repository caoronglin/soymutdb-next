#!/usr/bin/env tsx
/**
 * Embed release-pinned PageDefinitions into static pages (Phase 8).
 *
 * After the SPA assets and content pages are built, this script fetches the
 * published PageDefinition route(s) from the API and injects a
 * `#rl-page-definition` bootstrap `<script type="application/json">` into the
 * matching static HTML so the public renderer hydrates the definition without
 * a refetch (version match → no refetch; see src/page-builder/loader.ts).
 *
 * Offline / API-unavailable behaviour mirrors fetch-content-snapshot.ts:
 * local builds (and non-production CI) SKIP silently (exit 0) so the plain SPA
 * path and immutable seed fallback still work.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const API_BASE = process.env.SOYMUTDB_API_URL ?? "http://localhost:8000";
const DIST_DIR = join(process.cwd(), "dist");
const IS_PRODUCTION_BUILD =
  process.env.CI === "true" || process.env.NODE_ENV === "production";

/** Routes we embed bootstrap for (the SPA home + generic hub pages). */
const EMBED_ROUTES: ReadonlyArray<{ route: string; file: string }> = [
  { route: "/", file: "index.html" },
];

interface VersionPayload {
  version: number;
  status: string;
  definition: { title_key?: string; root: unknown };
}

function embedBootstrap(payload: Record<string, unknown>): string {
  const json = JSON.stringify(payload).replace(/</g, "\\u003c");
  return `<script type="application/json" id="rl-page-definition">${json}</script>`;
}

async function fetchDefinition(route: string): Promise<VersionPayload | null> {
  const normalized = route === "/" ? "" : route.replace(/^\/+/, "");
  const url = `${API_BASE}/api/v1/page-definitions/${normalized}`;
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    return (await res.json()) as VersionPayload;
  } catch {
    return null;
  }
}

function inject(html: string, bootstrap: string): string {
  const marker = "</head>";
  if (!html.includes(marker)) return html;
  return html.replace(marker, `${bootstrap}${marker}`);
}

async function main(): Promise<void> {
  let embedded = 0;
  for (const { route, file } of EMBED_ROUTES) {
    const target = join(DIST_DIR, file);
    const html = readFileSync(target, "utf-8");

    const payload = await fetchDefinition(route);
    if (!payload || payload.status !== "published" || !payload.definition?.root) {
      console.warn(
        `[embed-page-definitions] no published definition for ${route}; leaving ${file} on seed fallback`,
      );
      continue;
    }

    const bootstrap = embedBootstrap({
      route,
      version: payload.version,
      definition: payload.definition,
      generated_at: new Date().toISOString(),
    });
    writeFileSync(target, inject(html, bootstrap), "utf-8");
    embedded += 1;
    console.log(`[embed-page-definitions] embedded ${route} (v${payload.version}) into ${file}`);
  }

  if (embedded === 0 && IS_PRODUCTION_BUILD) {
    // A production CI build that cannot reach the API still ships SPA pages;
    // the seed fallback covers the renderer. Report but do not fail.
    console.warn("[embed-page-definitions] no definitions embedded (API unavailable)");
  }
}

main().catch((err) => {
  console.error("[embed-page-definitions] failed:", (err as Error).message);
  process.exitCode = 1;
});
