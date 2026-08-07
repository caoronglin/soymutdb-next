/**
 * SoyMutDB API client — fetch-based with request/response interceptors and auth.
 *
 * Reads the base URL from the VITE_API_BASE_URL environment variable, falling
 * back to "/api/v1". Auth tokens are attached from localStorage; 401 responses
 * clear the token and redirect to the login page.
 */

const TOKEN_KEY = "soymutdb_token";
const REFRESH_TOKEN_KEY = "soymutdb_refresh_token";

/** Resolved API base URL. */
export const apiBaseUrl =
    (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

/** Default request timeout in milliseconds (critical operations). */
const DEFAULT_TIMEOUT = 30_000;

/**
 * Centralised timeout presets — adjust here to change globally.
 *
 * - CRITICAL:      Auth, data submission, admin operations (30s)
 * - NON_CRITICAL:  Data fetching, stats, charts, lists (5s)
 * - FILE_TRANSFER: Uploads, downloads, large payloads (60s)
 */
export const TimeoutPresets = {
    CRITICAL: 30_000,
    NON_CRITICAL: 5_000,
    FILE_TRANSFER: 60_000,
} as const;

/** Check whether an error was caused by a request timeout. */
export function isTimeoutError(err: unknown): boolean {
    return err instanceof ApiError && err.code === "GATEWAY_TIMEOUT";
}

/**
 * Retry a request function on timeout, with exponential backoff.
 *
 * @param fn Request function returning a Promise
 * @param maxRetries Maximum number of retry attempts (default 1)
 * @returns The result of `fn`, or throws the last error
 */
export async function withRetry<T>(
    fn: () => Promise<T>,
    maxRetries = 1,
): Promise<T> {
    let lastErr: unknown;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (err) {
            lastErr = err;
            // Only retry on timeout; other errors fail immediately.
            if (!isTimeoutError(err) || attempt === maxRetries) throw err;
            // Exponential backoff: 500ms, 1000ms, ...
            await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
        }
    }
    throw lastErr;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
    /** JSON-serializable request body (for non-FormData requests). */
    json?: unknown;
    /** URL search params appended to the request URL. */
    params?: Record<string, unknown> | object;
    /** Abort timeout in milliseconds (default 30000). */
    timeoutMs?: number;
}

/** Typed API error with status code and optional response body. */
export class ApiError extends Error {
    status: number;
    code?: string;
    details?: unknown;

    constructor(message: string, status: number, code?: string, details?: unknown) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.code = code;
        this.details = details;
    }
}

function buildUrl(path: string, params?: Record<string, unknown> | object): string {
    const base = path.startsWith("http") ? path : `${apiBaseUrl}${path}`;
    if (!params) return base;
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null) continue;
        if (Array.isArray(value)) {
            for (const v of value) search.append(key, String(v));
        } else {
            search.set(key, String(value));
        }
    }
    const qs = search.toString();
    return qs ? `${base}?${qs}` : base;
}

function getAuthToken(): string | null {
    if (typeof localStorage === "undefined") return null;
    return localStorage.getItem(TOKEN_KEY);
}

/** Clear stored auth credentials (called on 401). */
export function clearAuth(): void {
    if (typeof localStorage === "undefined") return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/** Persist auth tokens after a successful login. */
export function setAuthTokens(accessToken: string, refreshToken?: string): void {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(TOKEN_KEY, accessToken);
    if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

function redirectToLogin(): void {
    if (typeof window === "undefined") return;
    const { pathname, search } = window.location;
    if (pathname.startsWith("/login")) return;
    const redirect = encodeURIComponent(`${pathname}${search}`);
    window.location.href = `/login?redirect=${redirect}`;
}

/**
 * Core request function. Merges auth headers, serializes JSON bodies, applies
 * a timeout via AbortController, and normalizes errors.
 */
export async function request<T>(
    path: string,
    options: RequestOptions = {},
): Promise<T> {
    const { json, params, timeoutMs = DEFAULT_TIMEOUT, headers, ...rest } = options;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const requestHeaders = new Headers(headers);
    const token = getAuthToken();
    if (token) requestHeaders.set("Authorization", `Bearer ${token}`);

    let body: BodyInit | undefined;
    if (json !== undefined) {
        if (!requestHeaders.has("Content-Type")) {
            requestHeaders.set("Content-Type", "application/json");
        }
        body = JSON.stringify(json);
    }

    let response: Response;
    try {
        response = await fetch(buildUrl(path, params), {
            ...rest,
            headers: requestHeaders,
            body,
            signal: controller.signal,
        });
    } catch (err) {
        clearTimeout(timer);
        if (err instanceof DOMException && err.name === "AbortError") {
            throw new ApiError("Request timed out", 408, "GATEWAY_TIMEOUT");
        }
        throw new ApiError(
            err instanceof Error ? err.message : "Network error",
            0,
            "NETWORK_ERROR",
        );
    }
    clearTimeout(timer);

    // Handle 401 by clearing auth and redirecting to login.
    if (response.status === 401) {
        clearAuth();
        redirectToLogin();
        throw new ApiError("Unauthorized", 401, "UNAUTHORIZED");
    }

    const contentType = response.headers.get("content-type") ?? "";
    const isJson = contentType.includes("application/json");
    const payload = isJson ? await response.json().catch(() => null) : null;

    if (!response.ok) {
        const message =
            (payload && typeof payload === "object" && "message" in payload
                ? String((payload as { message: unknown }).message)
                : null) ?? response.statusText ?? "Request failed";
        const code =
            payload && typeof payload === "object" && "code" in payload
                ? String((payload as { code: unknown }).code)
                : undefined;
        throw new ApiError(message, response.status, code, payload);
    }

    // Some endpoints (DELETE) return no content.
    if (response.status === 204 || payload === null) {
        return undefined as T;
    }
    return payload as T;
}

/**
 * Convenience HTTP method helpers.
 *
 * GET requests default to NON_CRITICAL timeout (5s) since they are typically
 * data-fetching operations. POST/PUT/PATCH/DELETE default to CRITICAL timeout
 * (30s) since they are data-submission / auth operations.
 * Override per-request with `timeoutMs`.
 */
export const http = {
    get: <T>(path: string, options?: RequestOptions) =>
        request<T>(path, {
            timeoutMs: TimeoutPresets.NON_CRITICAL,
            ...options,
            method: "GET",
        }),
    post: <T>(path: string, options?: RequestOptions) =>
        request<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "POST",
        }),
    put: <T>(path: string, options?: RequestOptions) =>
        request<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "PUT",
        }),
    patch: <T>(path: string, options?: RequestOptions) =>
        request<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "PATCH",
        }),
    delete: <T>(path: string, options?: RequestOptions) =>
        request<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "DELETE",
        }),
};

export default {
    request,
    http,
    apiBaseUrl,
    setAuthTokens,
    clearAuth,
    ApiError,
    TimeoutPresets,
    isTimeoutError,
    withRetry,
};
