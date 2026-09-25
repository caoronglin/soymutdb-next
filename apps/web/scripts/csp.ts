#!/usr/bin/env tsx
/**
 * CSP policy for the Vue portal build.
 *
 * The portal is a data-driven SPA whose documents are emitted by
 * `scripts/generate-static-routes.ts`, so there is no React SSG template here.
 * What both the documents and the `_headers` writer still need is the *same*
 * policy string, computed once, from the same origins — and the finalizer needs
 * the exact inverse of the attribute escaping so it can read a policy back out
 * of an emitted document before rewriting it.
 *
 * The origin/CSP decisions live in `@soymutdb/shared/deployment` so the Vite
 * config (which injects the `<meta>` into the SPA shell) and this module cannot
 * drift.
 */
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { loadEnv } from "vite";

import { buildCsp, requireDeploymentOrigin } from "@soymutdb/shared/deployment";

const here = dirname(fileURLToPath(import.meta.url));

function readBuildEnv(): Record<string, string> {
  // Same loader the Vite config uses, so a value the build saw is the value the
  // CSP is composed from.
  return loadEnv(process.env.NODE_ENV === "production" ? "production" : "development", here, "");
}

const env = readBuildEnv();
const CF_ANALYTICS_TOKEN = env["VITE_CLOUDFLARE_ANALYTICS_TOKEN"]?.trim() || undefined;
const minimalDeployment = (env["VITE_DEPLOYMENT_MODE"] ?? "").trim().toLowerCase() === "minimal";

/**
 * The policy every document's `<meta>` tag is rendered with and — until
 * `scripts/finalize-csp.ts` rewrites it with per-page hashes — the policy the
 * `_headers` file carries.
 */
export const CSP_CONTENT = buildCsp(
  {
    apiOrigin: requireDeploymentOrigin(
      env["VITE_API_BASE_URL"] ?? process.env["SOYMUTDB_API_URL"],
      "API",
    ),
    jbrowseOrigin: minimalDeployment
      ? undefined
      : requireDeploymentOrigin(
          env["VITE_JBROWSE_BASE_URL"] ?? env["VITE_JBROWSE_URL"],
          "JBrowse",
        ),
  },
  Boolean(CF_ANALYTICS_TOKEN),
);

export function escapeHtmlAttribute(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;")
    .replace(/`/g, "&#x60;");
}

/** Inverse of {@link escapeHtmlAttribute}; `&amp;` decodes last. */
export function decodeHtmlAttribute(value: string): string {
  return value
    .replace(/&#x27;/g, "'")
    .replace(/&#x60;/g, "`")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

export const APP_DIR = resolve(here, "..");
