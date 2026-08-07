/**
 * API layer — thin re-export of @soymutdb/api-client with app-side
 * conveniences: CSRF token attachment and 401 refresh-token handling.
 *
 * The underlying client already attaches the JWT from localStorage and
 * redirects to /login on 401. Here we add CSRF protection and a refresh
 * attempt before giving up on a 401.
 */
import {
    http,
    request,
    apiBaseUrl,
    setAuthTokens,
    clearAuth,
    ApiError,
    type RequestOptions,
} from "@soymutdb/api-client";

const REFRESH_ENDPOINT = "/auth/refresh";
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
 * Attempt to refresh the access token using the stored refresh token.
 * Returns true on success, false otherwise.
 */
async function tryRefresh(): Promise<boolean> {
    if (typeof localStorage === "undefined") return false;
    const refreshToken = localStorage.getItem("soymutdb_refresh_token");
    if (!refreshToken) return false;
    try {
        const res = await fetch(`${apiBaseUrl}${REFRESH_ENDPOINT}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;
        const data = (await res.json()) as { access_token?: string; refresh_token?: string };
        if (!data.access_token) return false;
        setAuthTokens(data.access_token, data.refresh_token ?? refreshToken);
        return true;
    } catch {
        return false;
    }
}

/**
 * Enhanced request: tries a refresh on 401 once, then retries the original
 * request. Falls back to clearing auth + redirect on second failure.
 */
export async function secureRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = options.method ?? "GET";
    const opts = withCsrf(options, method);
    try {
        return await request<T>(path, opts);
    } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
            const refreshed = await tryRefresh();
            if (refreshed) {
                return request<T>(path, opts);
            }
            clearAuth();
            // The underlying client already redirects to /login; rethrow for callers.
        }
        throw err;
    }
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
