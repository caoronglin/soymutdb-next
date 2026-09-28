#!/usr/bin/env tsx
/**
 * CSP finalizer — the last writer of the portal's Content-Security-Policy.
 *
 * ## Why this runs where it does
 *
 * The build chain is
 *
 *   Umi Max build → generate-static-routes → **finalize-csp**
 *     → optional gzip-compress → gen-sw → release-manifest
 *
 * Every step before this one *creates* HTML, and several of them inject inline
 * `<script>` blocks of their own. A hash computed any earlier would be a hash of
 * a document that no longer exists, and the CSP would block the very scripts it
 * was supposed to allow. So the hashes are computed here, after the last HTML
 * writer, and the compression/manifest steps run after this one so that the
 * bytes they hash and gzip are the final bytes.
 *
 * ## What it does
 *
 * 1. For each emitted document: hash its executable inline scripts and rewrite
 *    that page's `<meta http-equiv="Content-Security-Policy">` with those exact
 *    hashes, dropping `'unsafe-inline'`.
 * 2. Rewrite the `Content-Security-Policy:` line in `_headers` with the **union**
 *    of every page's hashes. An HTTP header covers the whole site, so it has to
 *    allow the union; the per-page meta stays exact, and the intersection the
 *    browser computes is therefore the page's own policy.
 *
 * ## Failure behaviour
 *
 * Fail-closed. A missing `_headers`, or a `_headers` without a CSP line, aborts
 * the build rather than quietly shipping a site whose header policy is unknown.
 * That is deliberate: the alternative is an artifact that looks fine and is
 * either wider or narrower than intended.
 *
 * Usage:  tsx scripts/finalize-csp.ts      (run for each variant by build-sites.ts)
 * Env:    SOYMUTDB_DIST_DIR   output directory (default `dist`)
 */

import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { composeCsp, parseCsp } from "@soymutdb/shared/build/csp";
// Node-only entry point: imports `node:crypto`, which is why it is separate
// from the portable `./csp` utilities the browser bundle also reaches.
import { collectInlineScriptHashes } from "@soymutdb/shared/build/csp-hash";
import { CSP_CONTENT, decodeHtmlAttribute, escapeHtmlAttribute } from "./csp";

const DIST_DIR = resolve(process.cwd(), process.env.SOYMUTDB_DIST_DIR ?? "dist");
const HEADERS_FILE = join(DIST_DIR, "_headers");

const META_RE =
  /(<meta\s+http-equiv="Content-Security-Policy"\s+content=")([^"]*)("\s*\/?>)/i;
const HEADERS_CSP_RE = /^([ \t]*Content-Security-Policy:[ \t]*)(\S.*)$/m;

function walkHtml(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) out.push(...walkHtml(full));
    else if (stat.isFile() && entry.endsWith(".html")) out.push(full);
  }
  return out;
}

/**
 * Replace `'unsafe-inline'` in script-src with the given hashes.
 *
 * The existing tokens are read back out of the base policy rather than rebuilt,
 * so a source added by `buildCsp()` — the Cloudflare beacon origin, for example
 * — cannot be silently dropped here.
 */
function withScriptHashes(policy: string, hashes: readonly string[]): string {
  const directives = parseCsp(policy);
  const scriptTokens = (directives.get("script-src") ?? []).filter(
    (token) => token !== "'unsafe-inline'",
  );
  const merged = [...new Set([...scriptTokens, ...hashes])];
  directives.set("script-src", merged);
  return composeCsp(Object.fromEntries(directives));
}

function main(): void {
  if (!existsSync(DIST_DIR)) {
    throw new Error(`[finalize-csp] ${DIST_DIR} does not exist — run the build first`);
  }
  if (!existsSync(HEADERS_FILE)) {
    throw new Error(
      `[finalize-csp] ${HEADERS_FILE} is missing. The portal ships a _headers file in ` +
        "public/; without it the Pages deployment would serve no security headers " +
        "and there would be nowhere to put the site-wide CSP. Refusing to continue.",
    );
  }

  const pages = walkHtml(DIST_DIR);
  if (pages.length === 0) {
    throw new Error(`[finalize-csp] no HTML documents under ${DIST_DIR}`);
  }

  const union = new Set<string>();
  let rewritten = 0;
  let withoutMeta = 0;

  for (const page of pages) {
    const html = readFileSync(page, "utf8");
    const hashes = collectInlineScriptHashes(html);
    for (const hash of hashes) union.add(hash);

    const match = META_RE.exec(html);
    if (!match) {
      // `renderRedirectTemplate` emits no <meta> CSP on purpose — those pages
      // carry no user data and are allowed by the header policy instead. Their
      // hashes still have to reach the union, which the loop above did.
      withoutMeta += 1;
      continue;
    }

    const current = decodeHtmlAttribute(match[2]);
    const next = withScriptHashes(current, hashes);
    if (next === current) continue;
    writeFileSync(
      page,
      html.replace(META_RE, (_full, head: string, _body: string, tail: string) =>
        `${head}${escapeHtmlAttribute(next)}${tail}`),
      "utf8",
    );
    rewritten += 1;
  }

  const headers = readFileSync(HEADERS_FILE, "utf8");
  const headerMatch = HEADERS_CSP_RE.exec(headers);
  if (!headerMatch) {
    throw new Error(
      `[finalize-csp] ${HEADERS_FILE} has no "Content-Security-Policy:" line to rewrite. ` +
        "The file is the single place the site-wide policy lives; a build that cannot " +
        "find it must not publish.",
    );
  }
  // The site-wide policy is composed from `CSP_CONTENT` — the same string the
  // pages' <meta> policies are built from — and NOT from the value already in
  // the file. The file's value is the conservative pre-finalization default
  // (same-origin only), so deriving from it would ship a header policy with no
  // API or JBrowse origin and every cross-origin request would be blocked. The
  // file is read only to locate the line and to prove it exists.
  const sitePolicy = withScriptHashes(CSP_CONTENT, [...union]);
  writeFileSync(
    HEADERS_FILE,
    headers.replace(HEADERS_CSP_RE, (_full, prefix: string) => `${prefix}${sitePolicy}`),
    "utf8",
  );

  console.log(
    `[finalize-csp] ${relative(process.cwd(), DIST_DIR)}: ${pages.length} documents, ` +
      `${union.size} distinct inline-script hash(es) in the site-wide union; ` +
      `${rewritten} meta policies rewritten, ${withoutMeta} page(s) without a meta policy ` +
      "(covered by the header policy)",
  );
}

try {
  main();
} catch (error) {
  console.error(String((error as Error)?.message ?? error));
  process.exit(1);
}
