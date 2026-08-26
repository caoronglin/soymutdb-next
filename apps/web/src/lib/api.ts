/**
 * API layer — thin re-export of @soymutdb/api-client.
 *
 * CSRF attachment is handled centrally in the shared transport's authRequest
 * (see packages/api-client/src/csrf.ts), so Web and Admin enforce identical
 * mutation protection. This module only exposes app-friendly aliases.
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

/**
 * Enhanced request: the shared transport's auth coordination (refresh-on-401,
 * single-flight refresh, logout events) plus central CSRF attachment.
 */
export async function secureRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return authRequest<T>(path, options);
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
