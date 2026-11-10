#!/usr/bin/env tsx
/**
 * CSP policy for the React/Umi portal build.
 *
 * The static-route generator copies Umi's application shell into each route
 * document. The same policy is used by those documents and `_headers`; the
 * finalizer may then add per-page inline-script hashes.
 */
import { buildCsp, requireDeploymentOrigin, resolveAnalyticsProvider } from "@soymutdb/shared/deployment";

// build-sites passes one explicit environment to Umi and every post-build step.
const env = process.env;
const analyticsToken =
  (env.SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN ?? env.VITE_CLOUDFLARE_ANALYTICS_TOKEN)?.trim() ||
  undefined;
// Same shared resolver as `apps/web/config/config.ts`: the CSP finalizer and the
// Umi config must agree on whether this build loads the Cloudflare beacon,
// otherwise the policy either blocks the beacon or permits an origin nothing
// uses. An invalid provider therefore fails the build here too.
const analytics = resolveAnalyticsProvider(env.SOYMUTDB_ANALYTICS_PROVIDER, analyticsToken);
const minimalDeployment = (env.VITE_DEPLOYMENT_MODE ?? "").trim().toLowerCase() === "minimal";
// Keep this aligned with `apps/web/config/config.ts`. An http preview origin is
// accepted by either `NODE_ENV=development` or the explicit local-test flag;
// when this file recognised only the first, `build-sites.ts` failed on an http
// preview origin that the Umi config had already accepted — the two halves of
// one build disagreed about the same environment.
const allowInsecureDevOrigins =
  env.NODE_ENV === "development" ||
  env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "true" ||
  env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "1";

const fileViewerUrl = env.VITE_FILE_VIEWER_URL?.trim() || undefined;

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
    frameOrigins: fileViewerUrl
      ? [
          requireDeploymentOrigin(fileViewerUrl, "File viewer", {
            allowInsecureHttp: allowInsecureDevOrigins,
          }),
        ]
      : [],
  },
  analytics.cloudflare,
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

