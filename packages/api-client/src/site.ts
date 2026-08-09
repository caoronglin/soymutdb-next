import { request } from "./client";

/**
 * Typed public site-information endpoints (D4).
 *
 *   GET /api/v1/site/about → SiteAbout
 *
 * Backed by the `about.*` rows in `system_settings` (edited via the admin
 * Settings UI). Every field is optional — a fresh deployment without the
 * rows returns null for each key. Response shape mirrors
 * apps/api/app/schemas/site.py (AboutContentResponse).
 */

/** Editable "About us" content (bilingual, all fields optional). */
export interface SiteAbout {
  title_en: string | null;
  title_zh: string | null;
  summary_en: string | null;
  summary_zh: string | null;
  content_en: string | null;
  content_zh: string | null;
}

/** Fetch the public "About us" content. */
export function getSiteAbout(): Promise<SiteAbout> {
  return request<SiteAbout>("/site/about", { auth: false });
}
