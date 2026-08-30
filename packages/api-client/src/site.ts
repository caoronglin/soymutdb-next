import { request } from "./client";
import { authRequest } from "./auth";

/**
 * Typed site variants.  The build pipeline selects one variant explicitly;
 * the client never guesses from hostname, headers, or visitor identity.
 */
export type SiteVariant = "external" | "internal";

export const SITE_VARIANTS = ["external", "internal"] as const satisfies readonly SiteVariant[];

function siteRequest<T>(path: string, variant: SiteVariant): Promise<T> {
  const options = { params: { variant } };
  return variant === "internal"
    ? authRequest<T>(path, options)
    : request<T>(path, { ...options, auth: false });
}

/** Editable About content (bilingual, all fields optional). */
export interface SiteAbout {
  title_en: string | null;
  title_zh: string | null;
  summary_en: string | null;
  summary_zh: string | null;
  content_en: string | null;
  content_zh: string | null;
}

/** Fetch the About content for one explicit site variant. */
export function getSiteAbout(variant: SiteVariant = "external"): Promise<SiteAbout> {
  return siteRequest<SiteAbout>("/site/about", variant);
}

/** Editable homepage welcome block (bilingual rich HTML, all fields optional). */
export interface SiteHome {
  welcome_en: string | null;
  welcome_zh: string | null;
}

/** Fetch the homepage welcome content for one explicit site variant. */
export function getSiteHome(variant: SiteVariant = "external"): Promise<SiteHome> {
  return siteRequest<SiteHome>("/site/home", variant);
}

/** Editable footer contact block (plain text, defaults filled by the API). */
export interface SiteFooter {
  contact_person: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  copyright: string | null;
  address: string | null;
}

/** Fetch the footer contact content for one explicit site variant. */
export function getSiteFooter(variant: SiteVariant = "external"): Promise<SiteFooter> {
  return siteRequest<SiteFooter>("/site/footer", variant);
}

/**
 * Editable frontend content (server-validated text and image URLs).
 *
 * The response remains a flat map for compatibility with useSiteContent; the
 * variant is an explicit query parameter and is isolated on the server.
 */
export type SiteContent = Record<string, string>;

/** Fetch the editable site-content map for one explicit site variant. */
export function getSiteContent(variant: SiteVariant = "external"): Promise<SiteContent> {
  return siteRequest<SiteContent>("/site/content", variant);
}
