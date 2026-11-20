/**
 * Routing policy for the optional remote preview provider (open-file-viewer
 * style). Previewing a file remotely means handing its bytes to a third
 * party, so the decision is a data-export decision, not a UI preference.
 *
 * The policy fails closed: anything not proven to be a released public
 * artifact with a time-limited https location, on a viewer explicitly
 * configured for *this* site variant, stays in the local renderer. In
 * particular a caller that does not state a visibility is treated as
 * internal, because a missing field means the record was not proven public.
 */
import type { SiteVariant } from "../../lib/site-variant";

export type PreviewVisibility = "public" | "internal";

export interface RemotePreviewConfig {
  /** The variant this provider was configured for; never cross-used. */
  siteVariant: SiteVariant;
  /**
   * HTTPS URL of the external viewer. A `{url}` placeholder receives the
   * encoded artifact location; without one the location is appended as a
   * `url=` query parameter.
   */
  viewerUrl: string;
  /** Object-storage/CDN origins the artifact URL may point at. */
  artifactOrigins: readonly string[];
}

export type PreviewRoute = { mode: "local" } | { mode: "remote"; url: string };

const LOCAL: PreviewRoute = { mode: "local" };

/** Signed-URL parameters that carry a positive lifetime in seconds. */
const EXPIRY_PARAMS = ["expires", "exp", "expiry", "x-amz-expires", "x-goog-expires"];

const BARE_INTEGER = /^\d+$/;

function asHttpsUrl(value: string | null | undefined): URL | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") return undefined;
    if (url.username || url.password) return undefined;
    return url;
  } catch {
    return undefined;
  }
}

function hasBoundedLifetime(url: URL): boolean {
  // Query parameter names are case-sensitive, and providers disagree
  // (`X-Amz-Expires` vs `expires`), so compare lowercased keys.
  for (const [key, raw] of url.searchParams) {
    if (!EXPIRY_PARAMS.includes(key.toLowerCase())) continue;
    if (!BARE_INTEGER.test(raw.trim())) continue;
    if (Number(raw) > 0) return true;
  }
  return false;
}

export interface PreviewRouteInput {
  siteVariant: SiteVariant;
  visibility: PreviewVisibility;
  config: RemotePreviewConfig | undefined;
  /** Artifact location offered by the API (pre-signed when available). */
  url: string | null | undefined;
}

export function resolvePreviewRoute({
  siteVariant,
  visibility,
  config,
  url,
}: PreviewRouteInput): PreviewRoute {
  if (!config || config.siteVariant !== siteVariant) return LOCAL;
  if (visibility !== "public") return LOCAL;

  const artifact = asHttpsUrl(url);
  if (!artifact || !hasBoundedLifetime(artifact)) return LOCAL;

  const allowedOrigins = new Set<string>();
  for (const candidate of config.artifactOrigins) {
    const parsed = asHttpsUrl(candidate);
    if (parsed) allowedOrigins.add(parsed.origin);
  }
  if (!allowedOrigins.has(artifact.origin)) return LOCAL;

  const viewer = asHttpsUrl(config.viewerUrl);
  if (!viewer) return LOCAL;

  const encoded = encodeURIComponent(artifact.toString());
  const remoteUrl = config.viewerUrl.includes("{url}")
    ? config.viewerUrl.replace("{url}", encoded)
    : `${config.viewerUrl}${config.viewerUrl.includes("?") ? "&" : "?"}url=${encoded}`;

  // The built URL is re-parsed: the template itself was validated as https,
  // and the encoded value cannot change scheme, host, or path.
  if (!asHttpsUrl(remoteUrl)) return LOCAL;
  return { mode: "remote", url: remoteUrl };
}