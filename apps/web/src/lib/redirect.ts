/**
 * Post-login redirect safety.
 *
 * `redirect` arrives as a query parameter, so it is attacker-controlled: a
 * crafted `/?redirect=https://evil.example` must never turn the login button
 * into an open redirect. The target is resolved against a placeholder origin on
 * the current browser, which also keeps subpath deployments working — the
 * router later pushes the pathname, not an absolute URL.
 */
export const SAFE_REDIRECT_ORIGIN = "https://soymutdb.invalid";

/** True when the value contains C0/C1 control characters or DEL. */
function hasControlCharacters(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

/** Return a same-site path for a post-login redirect, or "/" when unsafe. */
export function safeRedirect(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    hasControlCharacters(value) ||
    /^[a-z][a-z0-9+.-]*:/i.test(value)
  ) {
    return "/";
  }

  try {
    const target = new URL(value, SAFE_REDIRECT_ORIGIN);
    if (target.origin !== SAFE_REDIRECT_ORIGIN) return "/";
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return "/";
  }
}
