/**
 * API layer — thin re-export of @soymutdb/api-client with app-side
 * conveniences: CSRF token attachment.
 *
 * Auth coordination (refresh-on-401 via the HttpOnly cookie, single retry,
 * logout events, session restore) lives in the shared transport
 * (@soymutdb/api-client ./auth). This module only attaches the CSRF header
 * and exposes app-friendly aliases.
 */
import {
    authRequest,
    http,
    request,
    apiBaseUrl,
    setAuthTokens,
    clearAuth,
    ApiError,
    type RequestOptions,
} from "@soymutdb/api-client";

const CSRF_COOKIE_NAME = "soymutdb_csrf";
const CSRF_HEADER = "X-CSRF-Token";

/** Read a cookie by name (used for CSRF token extraction). */
function readCookie(name: string): string | null {
    if (typeof document === "undefined") return null;
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : null;
}

/** Attach CSRF token to unsafe methods. */
function withCsrf(options: RequestOptions, method: string): RequestOptions {
    const unsafe = ["POST", "PUT", "PATCH", "DELETE"];
    if (!unsafe.includes(method.toUpperCase())) return options;
    const csrf = readCookie(CSRF_COOKIE_NAME);
    if (!csrf) return options;
    return {
        ...options,
        headers: { ...options.headers, [CSRF_HEADER]: csrf },
    };
}

/**
 * Enhanced request: CSRF attachment on top of the shared transport's
 * auth coordination (401 → single-flight refresh → retry once; refresh
 * failure clears memory state and emits the logout event).
 */
export async function secureRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = options.method ?? "GET";
    return authRequest<T>(path, withCsrf(options, method));
}

/** HTTP helpers that route through the secure request wrapper. */
export const secureHttp = {
    get: <T>(path: string, options?: RequestOptions) =>
        secureRequest<T>(path, { ...options, method: "GET" }),
    post: <T>(path: string, options?: RequestOptions) =>
        secureRequest<T>(path, { ...options, method: "POST" }),
    put: <T>(path: string, options?: RequestOptions) =>
        secureRequest<T>(path, { ...options, method: "PUT" }),
    patch: <T>(path: string, options?: RequestOptions) =>
        secureRequest<T>(path, { ...options, method: "PATCH" }),
    delete: <T>(path: string, options?: RequestOptions) =>
        secureRequest<T>(path, { ...options, method: "DELETE" }),
};

export { http, request, apiBaseUrl, setAuthTokens, clearAuth, ApiError };
export type { RequestOptions };
