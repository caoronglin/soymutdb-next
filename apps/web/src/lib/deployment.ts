/**
 * Deployment-context resolution for the React portal (DB-CORE-5 / review R1).
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


export {
  buildJbrowseLocusUrl,
  isMinimalDeploymentMode,
  resolveAppUrl,
} from "@soymutdb/shared/deployment";

// normalizeBasePath and resolveSiteVariant live in zero-dependency modules so
// the Umi config can import them without loading the api-client; re-exported
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
 * Canonical origin the portal validates every incoming bridge message against.
 *
 * Derived from the same `VITE_JBROWSE_BASE_URL` the frame is loaded from, so the
 * origin in the URL and the origin in the validator cannot drift. A relative
 * base ("/jbrowse") resolves against the portal origin, which is also what a
 * same-origin deployment posts from; an absent document (prerender) falls back
 * to the portal origin rather than an unusable relative string.
 */
export function resolveJbrowseOrigin(value: unknown, portalOrigin: string): string {
  const base = resolveJbrowseBaseUrl(value);
  try {
    return new URL(base, portalOrigin || undefined).origin;
  } catch {
    return portalOrigin;
  }
}

/**
 * Optional-service feature gate.
 *
 * A core-only deployment ships the portal without services it does not run
 * (JBrowse, BLAST, …). Absent or any value other than an explicit
 * off-token keeps the service enabled, so existing deployments are unchanged;
 * only an explicit ``0``/``false``/``off``/``no`` disables it.
 */
export function resolveFeatureFlag(value: unknown, defaultEnabled = true): boolean {
  if (typeof value !== "string") return defaultEnabled;
  const normalized = value.trim().toLowerCase();
  if (["0", "false", "off", "no"].includes(normalized)) return false;
  if (["1", "true", "on", "yes"].includes(normalized)) return true;
  return defaultEnabled;
}
