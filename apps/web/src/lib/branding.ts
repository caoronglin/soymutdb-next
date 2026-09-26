/**
 * Runtime site branding.
 *
 * The bilingual name/icon snapshot is fetched for the explicitly selected site
 * variant and applied to the chrome (header wordmark, document title, favicon).
 * The static HTML ships the build-time defaults, and a failed or pending read
 * keeps them, so a brand outage never blanks the site identity. The internal
 * variant is `private, no-store` on the API side; this module never caches it
 * anywhere but the in-memory query cache.
 */
import { computed, type ComputedRef } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { getSiteBranding, type SiteBranding } from "@soymutdb/api-client";
import type { SupportedLanguage } from "@soymutdb/i18n-core";

import { currentLanguage } from "./i18n";
import { useSiteContextStore, type SiteVariant } from "../stores/site-context";

export const DEFAULT_SITE_NAME = "SoyMutDB";
export const DEFAULT_FAVICON_HREF = "/favicon.svg";

/**
 * Pick the display name for the active language.
 *
 * A deployment may fill only one language; the other language then falls back
 * to the filled field rather than showing an empty wordmark. The build default
 * is the last resort.
 */
export function resolveBrandName(
  brand: SiteBranding | undefined,
  language: SupportedLanguage,
): string {
  if (!brand) return DEFAULT_SITE_NAME;
  const primary = language === "zh" ? brand.name_zh : brand.name_en;
  const fallback = language === "zh" ? brand.name_en : brand.name_zh;
  return primary.trim() || fallback.trim() || DEFAULT_SITE_NAME;
}

export interface SiteBrandingState {
  displayName: ComputedRef<string>;
  iconUrl: ComputedRef<string | null>;
}

/** Read the brand snapshot for one explicit variant (defaults to the app's). */
export function useSiteBranding(variant?: SiteVariant): SiteBrandingState {
  const site = useSiteContextStore();
  const selected = variant ?? site.siteVariant;

  const query = useQuery({
    queryKey: computed(() => ["site", "branding", selected]),
    queryFn: () => getSiteBranding(selected),
    staleTime: 10 * 60_000,
    retry: false,
  });

  const displayName = computed(() =>
    resolveBrandName(query.data.value, currentLanguage.value),
  );
  const iconUrl = computed(() => query.data.value?.icon_url?.trim() || null);

  return { displayName, iconUrl };
}
