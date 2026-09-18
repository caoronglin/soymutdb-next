/**
 * JBrowse `_headers` origin injector.
 *
 * `apps/jbrowse/public/_headers` cannot hardcode its origins: the app is
 * embedded by the portal and the admin console, and it fetches the API and the
 * genomic-data plane. Which origins those are is a build-time fact. Without this
 * step the file shipped literal `api.example.com` / `portal.example.com` /
 * `admin.example.com` placeholders, so on Cloudflare Pages JBrowse's API calls
 * and every embed were blocked by its own CSP — the artifact looked correct and
 * simply did not work.
 *
 * Three sources are injected, and each one is a real requirement:
 *
 *   connect-src    + VITE_API_BASE_URL        (release API)
 *                  + VITE_JBROWSE_DATA_URL    (track data; only needed when it
 *                                              is a different origin)
 *   frame-ancestors+ SOYMUTDB_PORTAL_ORIGIN   (the portal embeds this app)
 *                  + SOYMUTDB_ADMIN_ORIGIN    (the admin console embeds it too)
 *
 * Fail-closed: a production build with a missing origin aborts instead of
 * publishing a policy that would block the app. Demo/standard builds accept the
 * `.invalid`/`.test` origins the other frontend gates already use, so the shared
 * verification script keeps working offline.
 *
 * Registered as a Vite plugin in apps/jbrowse/vite.config.ts. This file
 * deliberately has no `#!` line: Vite bundles the config with its imports
 * inlined, and a hashbang in an inlined module is a syntax error, not a
 * stripped comment.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { composeCsp, parseCsp } from "@soymutdb/shared/build/csp";

const HEADERS_PATH = resolve(process.cwd(), "dist/_headers");
const HEADERS_CSP_RE = /^([ \t]*Content-Security-Policy:[ \t]*)(\S.*)$/m;

const PLACEHOLDER_HOSTS = [
  "example.com",
  "example.org",
  "example.net",
  "localhost",
  "127.0.0.1",
];

/**
 * Normalizes an absolute origin.
 *
 * Returns `undefined` for a relative reference (`/jbrowse-data`, `jbrowse-data`),
 * which is the *normal* value for the data plane: a same-origin path needs no
 * CSP source because `'self'` already covers it. Callers that genuinely require
 * an origin check the result themselves.
 */
export function resolveOrigin(value: string | undefined, label: string, allowPlaceholder: boolean): string | undefined {
  const raw = value?.trim();
  if (!raw) return undefined;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(raw)) return undefined;

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`[jbrowse-headers] ${label} must be an absolute URL: ${raw}`);
  }
  if (url.protocol !== "https:" && !allowPlaceholder) {
    throw new Error(`[jbrowse-headers] ${label} must use https: ${raw}`);
  }
  if (!allowPlaceholder && PLACEHOLDER_HOSTS.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`))) {
    throw new Error(`[jbrowse-headers] ${label} uses a placeholder origin: ${raw}`);
  }
  // Only the origin is useful in a CSP source list; a path would be ignored and
  // a trailing slash would produce `https://host/` (not a valid source).
  return url.origin;
}

export interface InjectOptions {
  apiBaseUrl?: string;
  dataUrl?: string;
  portalOrigin?: string;
  adminOrigin?: string;
  /** Demo/standard builds allow `.invalid`/`.test` origins and plain http. */
  allowPlaceholderOrigins: boolean;
}

/**
 * Rewrites the CSP line in `_headers`.
 *
 * Exported so the contract test can exercise it against a fixture instead of a
 * real build.
 */
export function injectHeadersOrigins(options: InjectOptions, headersPath = HEADERS_PATH): void {
  const { allowPlaceholderOrigins: allow } = options;

  const apiOrigin = resolveOrigin(options.apiBaseUrl, "VITE_API_BASE_URL", allow);
  if (!apiOrigin) {
    throw new Error(
      "[jbrowse-headers] VITE_API_BASE_URL is required — without it connect-src " +
        "would be same-origin only and every API call from JBrowse would be blocked",
    );
  }

  // The data plane may be same-origin (the default relative `/jbrowse-data`), in
  // which case no extra source belongs in connect-src.
  const dataOrigin = resolveOrigin(options.dataUrl, "VITE_JBROWSE_DATA_URL", allow);

  const portalOrigin = resolveOrigin(options.portalOrigin, "SOYMUTDB_PORTAL_ORIGIN", allow);
  const adminOrigin = resolveOrigin(options.adminOrigin, "SOYMUTDB_ADMIN_ORIGIN", allow);
  if (!portalOrigin) {
    throw new Error(
      "[jbrowse-headers] SOYMUTDB_PORTAL_ORIGIN is required — frame-ancestors must " +
        "name the portal so the public UI can embed this app, and `'self'` alone " +
        "would block it on a separate hostname",
    );
  }

  if (!existsSync(headersPath)) {
    throw new Error(
      `[jbrowse-headers] ${headersPath} is missing. The app ships one in ` +
        "apps/jbrowse/public/; without it the Pages deployment serves no security " +
        "headers and there is nowhere to put the CSP.",
    );
  }

  const headers = readFileSync(headersPath, "utf8");
  const match = HEADERS_CSP_RE.exec(headers);
  if (!match) {
    throw new Error(`[jbrowse-headers] ${headersPath} has no Content-Security-Policy line to rewrite`);
  }

  // Rebuild from the existing directive map rather than from a template, so the
  // directives this app already declares (worker-src blob: for its workers,
  // img-src blob: for track images) are preserved exactly.
  const directives = parseCsp(match[2]);
  const connect = new Set(directives.get("connect-src") ?? ["'self'"]);
  connect.add(apiOrigin);
  if (dataOrigin && dataOrigin !== apiOrigin) connect.add(dataOrigin);
  directives.set("connect-src", [...connect]);

  const ancestors = new Set((directives.get("frame-ancestors") ?? ["'self'"]).map((t) => t));
  ancestors.add(portalOrigin);
  if (adminOrigin) ancestors.add(adminOrigin);
  directives.set("frame-ancestors", [...ancestors]);

  const policy = composeCsp(Object.fromEntries(directives));
  writeFileSync(headersPath, headers.replace(HEADERS_CSP_RE, (_m, prefix: string) => `${prefix}${policy}`), "utf8");
}

/** Vite plugin wrapper. */
export function jbrowseDeploymentHeaders(options: InjectOptions) {
  return {
    name: "soymutdb-jbrowse-deployment-headers",
    apply: "build" as const,
    closeBundle() {
      injectHeadersOrigins(options);
    },
  };
}
