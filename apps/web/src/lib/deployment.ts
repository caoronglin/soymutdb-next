export interface DeploymentOrigins {
  apiOrigin: string;
  jbrowseOrigin: string;
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
    `frame-src 'self' ${origins.jbrowseOrigin}`,
    "base-uri 'self'", "form-action 'self'", "frame-ancestors 'self'", "object-src 'none'", "worker-src 'self' blob:",
  ].join("; ");
}
