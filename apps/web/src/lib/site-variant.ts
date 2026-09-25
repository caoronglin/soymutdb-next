/**
 * Site-variant validation. Zero dependencies on purpose: vite.config.ts runs
 * this at config time, before any app module (including the api-client) is
 * loaded, so an illegal VITE_SITE_VARIANT fails the build instead of shipping a
 * third, unhandled variant.
 */

export type SiteVariant = "external" | "internal";

export function resolveSiteVariant(value: unknown): SiteVariant {
  if (value === undefined || value === null || value === "") return "external";
  if (value === "external" || value === "internal") return value;
  throw new Error(
    `VITE_SITE_VARIANT must be exactly "external" or "internal"; got ${JSON.stringify(value)}`,
  );
}
