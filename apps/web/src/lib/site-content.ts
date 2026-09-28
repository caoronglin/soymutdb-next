/**
 * Backend-editable site content for the Vue portal.
 *
 * The admin console stores `content_<variant>.<key>` rows (hero, tool cards,
 * nav labels, ...). This module is the portal-side reader those edits were
 * missing: React has had `lib/site-content.tsx` + `useSiteContent()` for a
 * while, so admins could already edit copy that the Vue portal never consumed.
 *
 * ---------------------------------------------------------------------------
 * WHY `onlyOverrides: true` (do not "simplify" it away)
 * ---------------------------------------------------------------------------
 * The `/site/content` endpoint fills EVERY registered key with its English
 * registered default when `only_overrides` is not sent. The portal is bilingual
 * and renders its own locale-aware `t(...)` strings, so "the server value always
 * wins" would replace a Chinese page's copy with the English default the moment
 * the request resolves — the portal would silently turn English.
 *
 * Asking for stored rows only (`SiteContentOptions.onlyOverrides` in
 * `packages/api-client/src/site.ts`) lets every call site render
 * `override ?? its own i18n string`:
 *
 *   - an unedited deployment stays byte-identical to today in every locale;
 *   - an operator's edit wins in every locale.
 *
 * The endpoint itself is variant-aware and public for `external`
 * (`request(..., auth:false)`) while `internal` goes through `authRequest`;
 * `getSiteContent` already owns that branch. An anonymous 401 on the internal
 * variant is treated as "no overrides" so the header/home still render.
 *
 * Contract (mirrors React, but override-only):
 *   useSiteContent() -> { data, get }
 *   get(key, fallback) -> override ?? fallback, never undefined
 * The `fallback` is the caller's localized `t(...)` string, not a passthrough:
 * keep it at every call site.
 */
import { computed, type ComputedRef } from "vue";
import { useQuery } from "@tanstack/vue-query";

import { getSiteContent, type SiteContent } from "@soymutdb/api-client";

import { useSiteContextStore, type SiteVariant } from "../stores/site-context";

export type { SiteContent };

export interface SiteContentState {
  /** The loaded override map; undefined while pending or when the read failed. */
  data: ComputedRef<SiteContent | undefined>;
  /**
   * Resolve an override key with the caller's localized fallback.
   *
   * @param key      short content key, e.g. "hero.title"
   * @param fallback value used when the key has no stored override; `""` when
   *                 omitted so the result is never undefined.
   */
  get: (key: string, fallback?: string) => string;
}

/**
 * Read the editable-content overrides for one explicit site variant.
 *
 * The variant is part of the query key: the external and internal deployments
 * have separate stored overrides and must never share a cache entry. A failed
 * read (offline, or an anonymous internal visitor getting a 401) degrades to an
 * empty map — callers then render their `t(...)` fallbacks.
 */
export function useSiteContent(variant?: SiteVariant): SiteContentState {
  const site = useSiteContextStore();
  const selected = computed(() => variant ?? site.siteVariant);

  const query = useQuery({
    queryKey: computed(() => ["site", "content", selected.value]),
    queryFn: () => getSiteContent(selected.value, { onlyOverrides: true }),
    // Copy changes on an admin's schedule, not per navigation.
    staleTime: 5 * 60_000,
    retry: false,
  });

  const data = computed<SiteContent | undefined>(() => query.data.value);

  function get(key: string, fallback?: string): string {
    const value = data.value?.[key];
    return value !== undefined ? value : (fallback ?? "");
  }

  return { data, get };
}
