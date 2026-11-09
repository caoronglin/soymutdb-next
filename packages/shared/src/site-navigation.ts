/**
 * Shared header-navigation document (isomorphic with
 * `apps/api/app/core/header_navigation.py`).
 *
 * The API is authoritative for validation; these types and limits let the Admin
 * editor build a well-formed document and surface bounds before a round-trip.
 */

export const HEADER_NAVIGATION_SCHEMA_VERSION = 1 as const;
export const MAX_HEADER_NAVIGATION_BYTES = 64 * 1024;
export const MAX_HEADER_GROUPS = 8;
export const MAX_HEADER_LINKS = 48;
export const MAX_HEADER_LABEL_LENGTH = 80;
export const MAX_HEADER_DESTINATION_LENGTH = 2048;

export type HeaderNavTarget = "internal" | "external";

export interface HeaderNavLink {
  id: string;
  label_en: string;
  label_zh: string;
  target: HeaderNavTarget;
  href: string;
  enabled: boolean;
  order: number;
  /** Server-owned feature flag; the link is hidden while the flag is off. */
  feature?: string | null;
}

export interface HeaderNavGroup {
  id: string;
  title_en: string;
  title_zh: string;
  enabled: boolean;
  order: number;
  links: HeaderNavLink[];
}

export interface HeaderNavDocument {
  schema_version: typeof HEADER_NAVIGATION_SCHEMA_VERSION;
  groups: HeaderNavGroup[];
}

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function isHeaderSlug(value: string): boolean {
  return SLUG.test(value);
}

export function countHeaderLinks(document: HeaderNavDocument): number {
  return document.groups.reduce((total, group) => total + group.links.length, 0);
}

/** Assign contiguous 0-based order values from the current array order. */
export function reindexHeaderNavigation(document: HeaderNavDocument): HeaderNavDocument {
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

/** Parse a stored JSON string into the editable document, or null when invalid. */
export function parseHeaderNavigationJson(value: string | null | undefined): HeaderNavDocument | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (!isRecord(parsed) || !Array.isArray(parsed.groups)) return null;
    if (parsed.schema_version !== HEADER_NAVIGATION_SCHEMA_VERSION) return null;
    const groups: HeaderNavGroup[] = [];
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
        links: entry.links.flatMap((link): HeaderNavLink[] => {
          if (!isRecord(link) || typeof link.id !== "string") return [];
          return [{
            id: link.id,
            label_en: String(link.label_en ?? ""),
            label_zh: String(link.label_zh ?? ""),
            target: link.target === "external" ? "external" : "internal",
            href: String(link.href ?? ""),
            enabled: link.enabled !== false,
            order: Number(link.order ?? 0),
            feature: typeof link.feature === "string" ? link.feature : null,
          }];
        }),
      });
    }
    return { schema_version: HEADER_NAVIGATION_SCHEMA_VERSION, groups };
  } catch {
    return null;
  }
}

/** Stable, bounded serialization used for the settings document value. */
export function serializeHeaderNavigation(document: HeaderNavDocument): string {
  return JSON.stringify(reindexHeaderNavigation(document));
}