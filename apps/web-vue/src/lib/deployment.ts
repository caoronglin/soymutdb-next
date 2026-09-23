/**
 * Deployment-context resolution for the Vue portal (DB-CORE-5 / review R1).
 *
 * Every value here is a build/runtime deployment decision, never inferred from
 * the host, IP, cookies, or user agent:
 *
 *   VITE_SITE_VARIANT          external | internal (validated, fail closed)
 *   VITE_SOYMUTDB_RELEASE_ID   the release every dynamic request is pinned to
 *   VITE_JBROWSE_BASE_URL      the canonical JBrowse origin
 *   VITE_BASE_URL              the deployment subpath for asset URLs
 *
 * The site variant is validated instead of cast: an unchecked cast would let
 * `VITE_SITE_VARIANT=External` (or any typo) create a third variant whose
 * `isInternal` is false, quietly serving internal-configured builds as if they
 * were external. A wrong value is a build/startup failure, not a fallback.
 */

import { setReleaseId as setClientReleaseId } from "@soymutdb/api-client";

// normalizeBasePath and resolveSiteVariant live in zero-dependency modules so
// the Vite config can import them without loading the api-client; re-exported
// here for the views and tests that already read them from the deployment
// context.
export { normalizeBasePath } from "./base-path";
export { resolveSiteVariant, type SiteVariant } from "./site-variant";

/** Normalize the build-time release pin; empty/absent means "server active". */
export function resolveInitialReleaseId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Canonical JBrowse origin. Mirrors the api-client's VITE_JBROWSE_BASE_URL so
 * the configured origin is honored instead of falling back to a localhost
 * default.
 */
export function resolveJbrowseBaseUrl(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") return "/jbrowse";
  return value.trim().replace(/\/+$/, "");
}

/**
 * Pin the release the api-client sends as `X-SoyMutDB-Release`. Called with the
 * same value the store exposes, so the release shown in the UI and the release
 * requested from the API can never disagree.
 */
export function applyDeploymentRelease(releaseId: string | null): void {
  setClientReleaseId(releaseId);
}
