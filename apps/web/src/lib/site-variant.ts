import type { SiteVariant } from "@soymutdb/api-client";

export type { SiteVariant };

/** Build-time variant validation; site identity is never inferred at runtime. */
export function resolveSiteVariant(value: unknown): SiteVariant {
  if (value === undefined || value === null || value === "") return "external";
  if (value === "external" || value === "internal") return value;
  throw new Error(
    `VITE_SITE_VARIANT must be exactly "external" or "internal"; got ${JSON.stringify(value)}`,
  );
}

const configuredVariant = String(import.meta.env?.VITE_SITE_VARIANT ?? "external").trim();
export const SITE_VARIANT = resolveSiteVariant(configuredVariant);
export const IS_INTERNAL_SITE = SITE_VARIANT === "internal";
