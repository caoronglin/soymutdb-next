/**
 * Deployment-origin and CSP helpers shared by the Umi configs, build scripts
 * and release gates.
 *
 * Framework-neutral on purpose: the React applications, their container builds
 * and release gates all read the same origin/CSP decisions from here.
 *
 * The CSP is composed through `@soymutdb/shared/build/csp` so every emitter
 * produces the same directive order and separators; see that module's header for
 * why hand-agreement between copies was not good enough.
 */
// Self-reference through the package name (Node "self-referencing a package
// using its name"): every consumer — the Umi config, build scripts and the
// browser bundle — resolves the CSP builder through the exports map, so there is
// exactly one resolution path and no relative-specifier ambiguity between the
// bundler and the Node/tsx loaders.
import { composeCsp } from "@soymutdb/shared/build/csp";

export interface DeploymentOrigins {
  apiOrigin: string;
  /** Omitted for the web-only minimal deployment, which ships no iframe app. */
  jbrowseOrigin?: string;
  /** Additional origins allowed to be framed (e.g. the opt-in remote file viewer). */
  frameOrigins?: readonly string[];
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
 * This local opt-in selects unpublished test data for the minimal search UI.
 * Deployment mode alone must never route a reduced public build to test data.
 */
export function isSearchTestPreviewEnabled(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

const MINIMAL_SEARCH_PATHS = new Set(["/search/genes", "/search/location"]);

/** Returns whether a route belongs to the two-feature minimal search surface. */
export function isMinimalSearchPath(pathname: string): boolean {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return MINIMAL_SEARCH_PATHS.has(normalized);
}

/**
 * Minimal mode sends the site root to gene search and all other routes back to
 * the same entry point. Existing route modules remain compiled for full builds.
 */
export function minimalSearchRedirect(pathname: string): "/search/genes" | null {
  return isMinimalSearchPath(pathname) ? null : "/search/genes";
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

export function normalizeBasePath(value: unknown): string {
  // Absent/foreign values normalize to the root rather than throwing: this runs
  // at Vite config time, where an unset env var is the normal case and a crash
  // there reports as an opaque "failed to load config".
  const trimmed = typeof value === "string" ? value.trim() : "";
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
  params: { assembly: string; locus: string; release?: string },
): { href: string } {
  const query = new URLSearchParams({
    assembly: params.assembly,
    locus: params.locus,
    ...(params.release ? { release: params.release } : {}),
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
  // Composed through the shared builder so this policy, the SSG template and the
  // `_headers` writer cannot drift in directive order or separators. The output
  // is byte-identical to the previous hand-built array (asserted by
  // deployment.test.ts) — the refactor is structural only.
  return composeCsp({
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      "'unsafe-inline'",
      ...(analytics ? ["https://static.cloudflareinsights.com"] : []),
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "https:"],
    "font-src": ["'self'", "data:"],
    "connect-src": [
      "'self'",
      origins.apiOrigin,
      ...(analytics ? ["https://cloudflareinsights.com"] : []),
    ],
    "frame-src": [
      ...new Set([
        "'self'",
        ...(origins.jbrowseOrigin ? [origins.jbrowseOrigin] : []),
        ...(origins.frameOrigins ?? []),
      ]),
    ],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'self'"],
    "object-src": ["'none'"],
    "worker-src": ["'self'", "blob:"],
  });
}

/**
 * Hosts accepted by the Vite and Umi development servers.
 *
 * Vite 6 and webpack-dev-server reject any request whose `Host` header is not allowlisted:
 *
 *   Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not allowed.
 *   To allow this host, add "cnb-38o-1k28dm5ta-001.cnb.space" to
 *   `server.allowedHosts` in Vite or `devServer.allowedHosts` in Umi.
 *
 * That is exactly what a cloud development environment hits: CNB proxies every
 * preview port through a generated `*.cnb.space` / `*.cnb.run` host, and the
 * hostname is different for every environment, so it cannot be listed by hand.
 *
 * Scope: development-server transport configuration only. Production builds do
 * not consult it, so no host becomes trusted in an artifact and no CSP changes.
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
    // configured port is already in the `Host` header the server compares against,
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
