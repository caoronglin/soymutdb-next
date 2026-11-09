/**
 * Runtime site identity owned by Admin.
 *
 * The database kind and bilingual brand are server settings, not build-time
 * constants: `GET /site/profile` and `GET /site/branding` are the public
 * projections. Both hooks fall back to the previous static identity while the
 * request is pending or if it fails, so an unreachable API never blanks the
 * header.
 */

import { useQuery } from "@tanstack/react-query";
import {
  getSiteBranding,
  getSiteProfile,
  type DatabaseKind,
  type SiteBranding,
} from "@soymutdb/api-client";
import { SITE_VARIANT } from "./site-variant";

export const DEFAULT_DATABASE_KIND: DatabaseKind = "genome";

/**
 * Translation key for a non-default database profile, or null when the
 * deployment presents as a plain genome database (the historical default).
 */
export function databaseKindLabelKey(kind: DatabaseKind): string | null {
  return kind === "genome" ? null : `site.databaseKind.${kind}`;
}

export interface BrandWordmarkParts {
  before: string;
  accent: string | null;
  after: string;
}

/**
 * Split the configured name around "Mut" so the default `SoyMutDB` keeps the
 * gradient accent it had before branding became editable. Custom names render
 * unchanged.
 */
export function brandWordmarkParts(name: string): BrandWordmarkParts {
  const marker = "Mut";
  const index = name.indexOf(marker);
  if (index < 0) return { before: name, accent: null, after: "" };
  return {
    before: name.slice(0, index),
    accent: marker,
    after: name.slice(index + marker.length),
  };
}

/** Admin-managed brand and database profile for the explicitly built variant. */
export function useSiteIdentity(): {
  branding: SiteBranding | undefined;
  databaseKind: DatabaseKind;
} {
  const branding = useQuery({
    queryKey: ["site-branding", SITE_VARIANT],
    queryFn: () => getSiteBranding(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });
  const profile = useQuery({
    queryKey: ["site-profile", SITE_VARIANT],
    queryFn: () => getSiteProfile(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });
  return {
    branding: branding.data,
    databaseKind: profile.data?.database_kind ?? DEFAULT_DATABASE_KIND,
  };
}