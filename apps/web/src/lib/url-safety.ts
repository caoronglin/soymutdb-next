/**
 * URL safety helpers for values that come from the API.
 *
 * Server responses are not a trusted source for an `href`/`window.open` target:
 * a stored location, a federated hit, or a CMS-managed link can carry any
 * scheme. Rendering one verbatim turns a data field into script execution
 * (`javascript:`) or an exfiltration channel (`data:`). These helpers allow only
 * the schemes a browser should ever navigate to for content this app serves.
 */

/** Schemes the client is willing to navigate to or embed. */
const NAVIGABLE_SCHEMES = new Set(["http:", "https:"]);

/**
 * Return `value` when it is an absolute `http:`/`https:` URL, otherwise
 * `undefined`.
 *
 * Relative URLs are deliberately rejected: every caller here is handling a
 * server-supplied location, and a relative value in that position means the
 * payload is malformed rather than that it means "same origin".
 */
export function safeExternalUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return NAVIGABLE_SCHEMES.has(url.protocol) ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** True when `value` is an absolute `http:`/`https:` URL. */
export function isSafeExternalUrl(value: string | null | undefined): boolean {
  return safeExternalUrl(value) !== undefined;
}
