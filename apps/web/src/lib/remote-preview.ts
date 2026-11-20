/**
 * Build-time configuration for the optional remote preview provider.
 *
 * Each artifact is built with at most one viewer: `build-sites.ts` maps the
 * variant-scoped, non-`VITE_` deployment inputs into this single pair, and
 * `config.ts` only inlines its whitelisted `viteEnv` object. Missing or partial
 * configuration disables remote preview entirely — the local renderer remains
 * the only route.
 */
import { SITE_VARIANT, type SiteVariant } from "./site-variant";
import type { RemotePreviewConfig } from "../components/file-viewer/preview-policy";

interface PreviewEnv {
  readonly VITE_FILE_VIEWER_URL?: string;
  readonly VITE_FILE_VIEWER_ARTIFACT_ORIGINS?: string;
}

export function resolveRemotePreviewConfig(
  siteVariant: SiteVariant,
  env: PreviewEnv,
): RemotePreviewConfig | undefined {
  const viewerUrl = String(env.VITE_FILE_VIEWER_URL ?? "").trim();
  const artifactOrigins = String(env.VITE_FILE_VIEWER_ARTIFACT_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter((origin) => origin.length > 0);

  if (!viewerUrl || artifactOrigins.length === 0) return undefined;
  return { siteVariant, viewerUrl, artifactOrigins };
}

export const REMOTE_PREVIEW_CONFIG = resolveRemotePreviewConfig(
  SITE_VARIANT,
  import.meta.env ?? {},
);