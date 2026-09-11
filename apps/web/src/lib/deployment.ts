export interface DeploymentOrigins {
  apiOrigin: string;
  /** Omitted for the web-only minimal deployment, which ships no iframe app. */
  jbrowseOrigin?: string;
}

/** Build-time deployment modes accepted by the public portal. */
export type DeploymentMode = "standard" | "demo" | "minimal" | "production";

/**
 * Normalize the optional Vite mode flag. Unknown values deliberately resolve to
 * the standard mode, which keeps the normal JBrowse-origin build requirement
 * rather than silently producing a reduced deployment.
 *
 * `production` is the strict production-build mode: it must bind a real
 * release and must NOT fall back to demo fixtures or embedded fallback data
 * when the release API is unavailable. See `isProductionDeploymentMode`.
 */
export function resolveDeploymentMode(value: string | undefined): DeploymentMode {
  switch (value?.trim().toLowerCase()) {
    case "demo":
      return "demo";
    case "minimal":
      return "minimal";
    case "production":
      return "production";
    default:
      return "standard";
  }
}

export function isMinimalDeploymentMode(value: string | undefined): boolean {
  return resolveDeploymentMode(value) === "minimal";
}

/**
 * True when the build is the strict production mode (`VITE_DEPLOYMENT_MODE`
 * set to `production`). In this mode:
 *   - a reachable release API is REQUIRED (SSG/sample generation must fail
 *     closed rather than fall back to embedded fixtures);
 *   - demo fallback pages (`fallback-data.ts`) must never enter the artifact;
 *   - a real `SOYMUTDB_RELEASE_ID` must be bound and a release manifest with
 *     SHA-256 digests must be emitted.
 */
export function isProductionDeploymentMode(value: string | undefined): boolean {
  return resolveDeploymentMode(value) === "production";
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

export function requireDeploymentOrigin(
  value: string | undefined,
  label: string,
  options: { allowInsecureHttp?: boolean } = {},
): string {
  const candidate = value?.trim();
  if (!candidate) throw new Error(`${label} origin is required for production deployment`);
  let url: URL;
  try { url = new URL(candidate); } catch { throw new Error(`${label} origin must be an absolute URL: ${candidate}`); }
  if (
    !options.allowInsecureHttp &&
    url.protocol !== "https:" &&
    url.hostname !== "localhost" &&
    url.hostname !== "127.0.0.1"
  ) {
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

/**
 * Hosts the Vite development server accepts.
 *
 * Vite 6 rejects any request whose `Host` header is not allowlisted:
 *
 *   Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not allowed.
 *   To allow this host, add "cnb-38o-1k28dm5ta-001.cnb.space" to
 *   `server.allowedHosts` in vite.config.js.
 *
 * That is exactly what a cloud development environment hits: CNB proxies every
 * preview port through a generated `*.cnb.space` / `*.cnb.run` host, and the
 * hostname is different for every environment, so it cannot be listed by hand.
 *
 * Scope: `server` (and `preview`) only. This is a development-server transport
 * rule and is never consulted by `vite build`, so no host becomes trustworthy
 * in a built artifact and no CSP changes with it.
 *
 * Security: `allowedHosts: true` would accept ANY hostname, which turns a
 * forwarded preview URL into a DNS-rebinding pivot. The generated platform
 * domains are matched exactly instead, and anything else must be listed
 * explicitly in `SOYMUTDB_DEV_ALLOWED_HOSTS` (comma/space separated, `*` globs
 * supported) — an opt-in extension, not a wildcard.
 */
const CNB_DEV_HOST_SUFFIXES = [".cnb.space", ".cnb.run"] as const;

/** Bare platform apexes. `*.cnb.space` does NOT match `cnb.space` itself. */
const CNB_DEV_HOSTS = ["cnb.space", "cnb.run", "localhost", "127.0.0.1", "[::1]"] as const;

function normalizeDevHost(entry: string): string {
    const value = entry.trim().replace(/^https?:\/\//i, "");
    if (!value) return "";
    // Drop anything after the host: a path, a query or a `:port` suffix. The
    // configured port is already in the `Host` header Vite compares against,
    // so keeping it would make a working entry silently not match.
    return value.replace(/[/?#].*$/, "").replace(/:\d+$/, "").toLowerCase();
}

export function resolveDevAllowedHosts(value: string | undefined): true | string[] {
    const raw = value?.trim();
    // `true` here is an explicit "I know what I am doing" for a non-CNB tunnel
    // that cannot be enumerated. It is never the default.
    if (raw === "true" || raw === "*") return true;

    const hosts = new Set<string>([...CNB_DEV_HOSTS, ...CNB_DEV_HOST_SUFFIXES]);
    for (const entry of (raw ?? "").split(/[\s,]+/)) {
        const host = normalizeDevHost(entry);
        if (host) hosts.add(host);
    }
    return [...hosts];
}
