#!/usr/bin/env tsx
/** Embed published PageDefinition bootstraps into release static HTML. */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export interface PublishedRoute {
  route: string;
  version: number;
  status: string;
  definition: { title_key?: string; root: unknown };
}

export interface EmbedOptions {
  apiBase: string;
  distDir: string;
  production?: boolean;
  fetchImpl?: typeof fetch;
}

function embedBootstrap(payload: Record<string, unknown>): string {
  const json = JSON.stringify(payload).replace(/</g, "\\u003c");
  return `<script type="application/json" id="rl-page-definition">${json}</script>`;
}

async function fetchPublishedRoutes(apiBase: string, fetchImpl: typeof fetch): Promise<PublishedRoute[]> {
  try {
    const res = await fetchImpl(`${apiBase}/api/v1/page-definitions/published-routes`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return [];
    const payload = (await res.json()) as unknown;
    return Array.isArray(payload) ? payload as PublishedRoute[] : [];
  } catch {
    return [];
  }
}

/** Reject traversal, empty segments, and non-URL-safe route segments. */
export function routeToFile(route: string): string | null {
  if (route === "/") return "index.html";
  if (!route.startsWith("/") || route.includes("//")) return null;
  const segments = route.slice(1).split("/");
  if (!segments.length || segments.some((segment) => !/^[a-z0-9][a-z0-9-]*$/i.test(segment))) return null;
  return join(...segments, "index.html");
}

function inject(html: string, bootstrap: string): string {
  return html.includes("</head>") ? html.replace("</head>", bootstrap + "</head>") : html;
}

/**
 * Generates one SPA-shell HTML file per published PageDefinition route.
 * An unreachable or empty public manifest is non-fatal: the existing SPA
 * output remains usable, including in offline local builds.
 */
export async function embedPublishedDefinitions(options: EmbedOptions): Promise<number> {
  const routes = await fetchPublishedRoutes(options.apiBase, options.fetchImpl ?? fetch);
  if (routes.length === 0) {
    console.warn("[embed-page-definitions] no published routes received; leaving SPA fallback intact");
    return 0;
  }

  const shellPath = join(options.distDir, "index.html");
  if (!existsSync(shellPath)) throw new Error(`missing SPA shell ${shellPath}`);
  const shell = readFileSync(shellPath, "utf-8");
  let embedded = 0;
  for (const payload of routes) {
    const file = routeToFile(payload.route);
    if (!file || payload.status !== "published" || !payload.definition?.root) {
      console.warn(`[embed-page-definitions] ignoring invalid unpublished route ${payload.route}`);
      continue;
    }
    const target = join(options.distDir, file);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, inject(shell, embedBootstrap({
      route: payload.route,
      version: payload.version,
      status: payload.status,
      definition: payload.definition,
      generated_at: new Date().toISOString(),
    })), "utf-8");
    embedded += 1;
    console.log(`[embed-page-definitions] embedded ${payload.route} (v${payload.version}) into ${file}`);
  }
  if (embedded === 0 && options.production) {
    console.warn("[embed-page-definitions] no valid published definitions embedded");
  }
  return embedded;
}

async function main(): Promise<void> {
  await embedPublishedDefinitions({
    apiBase: process.env.SOYMUTDB_API_URL ?? "http://localhost:8000",
    distDir: resolve(process.cwd(), process.env.SOYMUTDB_DIST_DIR ?? "dist"),
    production: process.env.CI === "true" || process.env.NODE_ENV === "production",
  });
}

if (process.argv[1]?.endsWith("embed-page-definitions.ts")) {
  main().catch((err) => {
    console.error("[embed-page-definitions] failed:", (err as Error).message);
    process.exitCode = 1;
  });
}
