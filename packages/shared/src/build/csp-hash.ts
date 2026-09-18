/**
 * Inline-script hashing for Content-Security-Policy — Node-only.
 *
 * Split out of `./csp` because it imports `node:crypto` while `./csp` is
 * reachable from the browser bundle (the SPA imports src/lib/deployment.ts for
 * its URL helpers, and that module composes its CSP through `./csp`). Keeping
 * them together broke the client build:
 *
 *   "createHash" is not exported by "__vite-browser-external"
 *
 * Only build scripts and their tests import this module.
 */

import { createHash } from "node:crypto";

/** Script `type` values that the browser executes. Absent `type` means classic JS. */
const EXECUTABLE_SCRIPT_TYPES = new Set([
  "text/javascript",
  "application/javascript",
  "module",
]);

/**
 * Hash every executable inline `<script>` in a document, per CSP's
 * `script-src 'sha256-…'` rules.
 *
 * Three details are load-bearing, and each was a bug in the naive version:
 *
 *   * **Only executable blocks.** `application/ld+json` and the
 *     `application/json` bootstrap payload are not scripts the browser runs, so
 *     hashing them bloats the policy with entries that can never match a
 *     request. They are skipped by `type`.
 *   * **The script text itself, not the tag.** The digest covers exactly the
 *     bytes between `>` and `</script>`, which is what the browser hashes.
 *   * **No entity decoding.** The document is a template result, not
 *     user input: the text is inserted verbatim by `renderBaseTemplate`, so
 *     decoding would hash different bytes than the browser sees.
 */
export function collectInlineScriptHashes(html: string): string[] {
  const hashes = new Set<string>();
  const scriptRe = /<script([^>]*)>([\s\S]*?)<\/script>/gi;
  for (const match of html.matchAll(scriptRe)) {
    const attrs = match[1] ?? "";
    if (/\bsrc\s*=/i.test(attrs)) continue;
    const typeMatch = /\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(attrs);
    const type = (typeMatch?.[1] ?? typeMatch?.[2] ?? typeMatch?.[3] ?? "").trim().toLowerCase();
    if (type && !EXECUTABLE_SCRIPT_TYPES.has(type)) continue;
    hashes.add(sha256Source(match[2] ?? ""));
  }
  return [...hashes];
}

/** `sha256-<base64>` for a CSP source expression. */
export function sha256Source(body: string): string {
  return `sha256-${createHash("sha256").update(body, "utf8").digest("base64")}`;
}
