/**
 * CSRF token attachment for cookie-authenticated mutations.
 *
 * The backend sets the `soymutdb_csrf` cookie; unsafe methods (POST/PUT/PATCH/
 * DELETE) must echo it back in the `X-CSRF-Token` header. This module is
 * transport-agnostic and shared by Web and Admin so both surfaces enforce the
 * same protection (no app-local ad-hoc bypass).
 */
import type { RequestOptions } from "./client";

const CSRF_COOKIE_NAME = "soymutdb_csrf";
const CSRF_HEADER = "X-CSRF-Token";

/** Read a cookie by name (SSR-safe). */
function readCookie(name: string): string | null {
    if (typeof document === "undefined") return null;
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Attach the CSRF token to unsafe methods. Safe methods (GET/HEAD/OPTIONS)
 * pass through unchanged.
 */
export function attachCsrf(options: RequestOptions, method: string): RequestOptions {
    const unsafe = ["POST", "PUT", "PATCH", "DELETE"];
    if (!unsafe.includes(method.toUpperCase())) return options;
    const csrf = readCookie(CSRF_COOKIE_NAME);
    if (!csrf) return options;
    return {
        ...options,
        headers: { ...options.headers, [CSRF_HEADER]: csrf },
    };
}
