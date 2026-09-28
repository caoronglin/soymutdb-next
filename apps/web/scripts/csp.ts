#!/usr/bin/env tsx
/**
 * CSP policy for the React/Umi portal build.
 *
 * The static-route generator copies Umi's application shell into each route
 * document. The same policy is used by those documents and `_headers`; the
 * finalizer may then add per-page inline-script hashes.
 */
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { buildCsp, requireDeploymentOrigin } from "@soymutdb/shared/deployment";

const here = dirname(fileURLToPath(import.meta.url));
// build-sites passes one explicit environment to Umi and every post-build step.
const env = process.env;
const analyticsToken = env.VITE_CLOUDFLARE_ANALYTICS_TOKEN?.trim() || undefined;
const minimalDeployment = (env.VITE_DEPLOYMENT_MODE ?? "").trim().toLowerCase() === "minimal";
const allowInsecureDevOrigins = env.NODE_ENV === "development";

/** CSP for every document and the `_headers` file before inline hashes are added. */
export const CSP_CONTENT = buildCsp(
  {
    apiOrigin: requireDeploymentOrigin(
      env.VITE_API_BASE_URL ?? env.SOYMUTDB_API_URL,
      "API",
      { allowInsecureHttp: allowInsecureDevOrigins },
    ),
    jbrowseOrigin: minimalDeployment
      ? undefined
      : requireDeploymentOrigin(
          env.VITE_JBROWSE_BASE_URL ?? env.VITE_JBROWSE_URL,
          "JBrowse",
          { allowInsecureHttp: allowInsecureDevOrigins },
        ),
  },
  Boolean(analyticsToken),
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
