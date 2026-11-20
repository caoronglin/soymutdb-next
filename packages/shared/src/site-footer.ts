/**
 * Shared footer-navigation document (isomorphic with
 * `apps/api/app/core/footer_content.py`).
 *
 * The API is authoritative for validation; these types and limits let the Admin
 * footer editor build a well-formed document and surface bounds before a
 * round-trip. The shape is identical to the header document so the two editors
 * can share their row model, but the limits are the footer's own.
 */

export const FOOTER_NAVIGATION_SCHEMA_VERSION = 1 as const;
export const MAX_FOOTER_NAVIGATION_BYTES = 32 * 1024;
export const MAX_FOOTER_GROUPS = 6;
export const MAX_FOOTER_LINKS = 32;
export const MAX_FOOTER_LABEL_LENGTH = 80;
export const MAX_FOOTER_DESTINATION_LENGTH = 2048;

export type FooterNavTarget = "internal" | "external";

export interface FooterNavLink {
  id: string;
  label_en: string;
  label_zh: string;
  target: FooterNavTarget;
  href: string;
  enabled: boolean;
  order: number;
}

export interface FooterNavGroup {
  id: string;
  title_en: string;
  title_zh: string;
  enabled: boolean;
  order: number;
  links: FooterNavLink[];
}

export interface FooterNavDocument {
  schema_version: typeof FOOTER_NAVIGATION_SCHEMA_VERSION;
  groups: FooterNavGroup[];
}

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function isFooterSlug(value: string): boolean {
  return SLUG.test(value);
}

export function countFooterLinks(document: FooterNavDocument): number {
  return document.groups.reduce((total, group) => total + group.links.length, 0);
}

/** Assign contiguous 0-based order values from the current array order. */
export function reindexFooterNavigation(document: FooterNavDocument): FooterNavDocument {
  return {
    ...document,
    groups: document.groups.map((group, groupIndex) => ({
      ...group,
      order: groupIndex,
      links: group.links.map((link, linkIndex) => ({ ...link, order: linkIndex })),
    })),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Parse a stored JSON string into the editable document, or null when it is not
 * a footer document this client can edit. The server re-validates on save.
 */
export function parseFooterNavigationJson(
  value: string | null | undefined,
): FooterNavDocument | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (!isRecord(parsed) || !Array.isArray(parsed.groups)) return null;
    if (parsed.schema_version !== FOOTER_NAVIGATION_SCHEMA_VERSION) return null;
    const groups: FooterNavGroup[] = [];
    for (const entry of parsed.groups) {
      if (!isRecord(entry) || typeof entry.id !== "string" || !Array.isArray(entry.links)) {
        return null;
      }
      groups.push({
        id: entry.id,
        title_en: String(entry.title_en ?? ""),
        title_zh: String(entry.title_zh ?? ""),
        enabled: entry.enabled !== false,
        order: Number(entry.order ?? 0),
        links: entry.links.flatMap((link): FooterNavLink[] => {
          if (!isRecord(link) || typeof link.id !== "string") return [];
          return [{
            id: link.id,
            label_en: String(link.label_en ?? ""),
            label_zh: String(link.label_zh ?? ""),
            target: link.target === "external" ? "external" : "internal",
            href: String(link.href ?? ""),
            enabled: link.enabled !== false,
            order: Number(link.order ?? 0),
          }];
        }),
      });
    }
    return { schema_version: FOOTER_NAVIGATION_SCHEMA_VERSION, groups };
  } catch {
    return null;
  }
}

/** Stable, bounded serialization used for the settings document value. */
export function serializeFooterNavigation(document: FooterNavDocument): string {
  return JSON.stringify(reindexFooterNavigation(document));
}