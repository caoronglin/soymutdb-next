export interface DeploymentOrigins {
  apiOrigin: string;
  /** Omitted for the web-only minimal deployment, which ships no iframe app. */
  jbrowseOrigin?: string;
}

/** Build-time deployment modes accepted by the public portal. */
export type DeploymentMode = "standard" | "demo" | "minimal";

/**
 * Normalize the optional Vite mode flag. Unknown values deliberately resolve to
 * the standard mode, which keeps the normal JBrowse-origin build requirement
 * rather than silently producing a reduced deployment.
 */
export function resolveDeploymentMode(value: string | undefined): DeploymentMode {
  switch (value?.trim().toLowerCase()) {
    case "demo":
      return "demo";
    case "minimal":
      return "minimal";
    default:
      return "standard";
  }
}

export function isMinimalDeploymentMode(value: string | undefined): boolean {
  return resolveDeploymentMode(value) === "minimal";
}

export function normalizeBasePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "/") return "/";
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}/`;
}

export function resolveAssetUrl(base: string, asset: string, _documentPath?: string): string {
  return `${normalizeBasePath(base)}${asset.replace(/^\/+/, "")}`;
}

export function resolveAppUrl(base: string, path: string): string {
  return resolveAssetUrl(base, path);
}

/**
 * Build a base-aware JBrowse 2 deep link for the `/browser` route.
 *
 * Anchored with the deployment base path so GitHub Pages / Cloudflare
 * subpath deploys resolve correctly (unlike root-relative `/browser`). The
 * `/browser` route reads `assembly` + `locus` (format `chr:start-end`).
 */
export function buildJbrowseLocusUrl(
  base: string,
  params: { assembly: string; locus: string },
): { href: string } {
  const query = new URLSearchParams({
    assembly: params.assembly,
    locus: params.locus,
  });
  return { href: `${normalizeBasePath(base)}browser?${query.toString()}` };
}

export function requireDeploymentOrigin(value: string | undefined, label: string): string {
  const candidate = value?.trim();
  if (!candidate) throw new Error(`${label} origin is required for production deployment`);
  let url: URL;
  try { url = new URL(candidate); } catch { throw new Error(`${label} origin must be an absolute URL: ${candidate}`); }
  if (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
    throw new Error(`${label} origin must use https: ${candidate}`);
  }
  if (url.hostname.endsWith("example.com")) throw new Error(`${label} origin uses a placeholder origin: ${candidate}`);
  return url.origin;
}

export function buildCsp(origins: DeploymentOrigins, analytics = false): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${analytics ? " https://static.cloudflareinsights.com" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    `connect-src 'self' ${origins.apiOrigin}${analytics ? " https://cloudflareinsights.com" : ""}`,
    `frame-src 'self'${origins.jbrowseOrigin ? ` ${origins.jbrowseOrigin}` : ""}`,
    "base-uri 'self'", "form-action 'self'", "frame-ancestors 'self'", "object-src 'none'", "worker-src 'self' blob:",
  ].join("; ");
}
