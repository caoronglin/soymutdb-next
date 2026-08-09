import { request } from "./client";

/**
 * Typed public site-information endpoints (D4).
 *
 *   GET /api/v1/site/about → SiteAbout
 *   GET /api/v1/site/home  → SiteHome
 *
 * Backed by the `about.*` / `home.*` rows in `system_settings` (edited via
 * the admin Settings UI). Every field is optional — a fresh deployment
 * without the rows returns null for each key. Response shapes mirror
 * apps/api/app/schemas/site.py (AboutContentResponse / HomeContentResponse).
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

/** Editable homepage welcome block (bilingual rich HTML, all fields optional). */
export interface SiteHome {
  welcome_en: string | null;
  welcome_zh: string | null;
}

/** Fetch the public homepage welcome content. */
export function getSiteHome(): Promise<SiteHome> {
  return request<SiteHome>("/site/home", { auth: false });
}
