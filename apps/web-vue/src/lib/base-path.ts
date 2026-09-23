/**
 * Deployment subpath normalization. Zero dependencies on purpose: the Vite
 * config imports this module, and pulling the api-client (or any other runtime
 * module) into the config loader would break the build.
 *
 * `base` in vite.config.ts and the router's createWebHistory(import.meta.env
 * .BASE_URL) both derive from VITE_BASE_URL, so emitted asset URLs, router
 * links, and deep links agree under `/` and under `/soymutdb-next/`.
 */

const TRAILING_SLASHES = /^\/+|\/+$/g;

export function normalizeBasePath(value: unknown): string {
  const trimmed = typeof value === "string" ? value.trim() : "";
  if (!trimmed || trimmed === "/") return "/";
  return `/${trimmed.replace(TRAILING_SLASHES, "")}/`;
}
