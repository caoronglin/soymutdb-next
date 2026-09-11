import type { SiteVariant } from "@soymutdb/api-client";

/**
 * Explicit build-time site selection.  Unknown values fail safe to external
 * in the browser; the production build config rejects them before emitting an
 * artifact.  No visitor/request signal is consulted.
 */
const configuredVariant = String(import.meta.env.VITE_SITE_VARIANT ?? "external")
  .trim()
  .toLowerCase();

export const SITE_VARIANT: SiteVariant = configuredVariant === "internal"
  ? "internal"
  : "external";

export const IS_INTERNAL_SITE = SITE_VARIANT === "internal";

export const SITE_VARIANT_LABELS: Record<SiteVariant, string> = {
  external: "External site",
  internal: "Internal site",
};

export const SITE_VARIANT_LABELS_ZH: Record<SiteVariant, string> = {
  external: "外部站点",
  internal: "内部站点",
};
