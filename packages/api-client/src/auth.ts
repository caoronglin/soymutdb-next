/**
 * SoyMutDB API client — auth coordination layer (module singleton).
 *
 * Owns everything the pure transport in ./client.ts deliberately does not:
 *
 *   - in-memory session state (the access token itself lives in client.ts)
 *   - refresh-on-401 with a single-flight refresh (concurrent 401s share one
 *     in-flight attempt) and at most one retry per request
 *   - logout events fired when a refresh fails mid-session (once per
 *     unauthenticated period; app layers register callbacks via
 *     `onAuthLogout` — no router is hardcoded here)
 *   - boot-time session restore from the HttpOnly refresh cookie
 *   - one-time migration that drops legacy persisted tokens
 *
 * The refresh request hits `<base>/auth/refresh`, which resolves to
 * `/api/v1/auth/refresh` — under the cookie Path `/api/v1/auth` set by the
 * backend. It carries no body (the refresh token is read from the cookie)
 * and uses `credentials: "include"`.
 */
import {
    request,
    apiBaseUrl,
    ApiError,
    TimeoutPresets,
    setAuthTokens,
    clearAuth,
    type RequestOptions,
} from "./client";

/** Refresh endpoint (resolves to <apiBaseUrl>/auth/refresh). */
export const AUTH_REFRESH_PATH = "/auth/refresh";

/** Legacy persisted-token keys removed during the one-time migration. */
const LEGACY_TOKEN_KEYS = [
    "soymutdb_token",
    "soymutdb_refresh_token",
    "soymutdb_access_token",
] as const;

/** Shape of the refresh response (subset of the OpenAPI TokenResponse). */
interface RefreshResponse {
    access_token: string;
    token_type?: string;
    expires_in?: number;
}

type LogoutHandler = () => void;

const logoutHandlers = new Set<LogoutHandler>();
let logoutEmitted = false;
let refreshInFlight: Promise<boolean> | null = null;

/**
 * Register a handler invoked when the session dies (refresh failure while
 * handling a 401). Returns an unsubscribe function.
 */
export function onAuthLogout(handler: LogoutHandler): () => void {
    logoutHandlers.add(handler);
    return () => {
        logoutHandlers.delete(handler);
    };
}

/**
 * One-time migration: remove legacy access/refresh token keys from both
 * localStorage and sessionStorage. Tokens are now held in module memory and
 * sessions are restored from the HttpOnly refresh cookie.
 */
export function clearLegacyTokens(): void {
    if (typeof localStorage !== "undefined") {
        for (const key of LEGACY_TOKEN_KEYS) {
            try {
                localStorage.removeItem(key);
            } catch {
                /* storage unavailable — ignore */
            }
        }
    }
    if (typeof sessionStorage !== "undefined") {
        for (const key of LEGACY_TOKEN_KEYS) {
            try {
                sessionStorage.removeItem(key);
            } catch {
                /* storage unavailable — ignore */
            }
        }
    }
}

async function performRefresh(): Promise<boolean> {
    try {
        const res = await request<RefreshResponse>(AUTH_REFRESH_PATH, {
            method: "POST",
            // The refresh token lives in the HttpOnly cookie — never send a
            // (possibly stale) Bearer header with the refresh call.
            auth: false,
            withCredentials: true,
            timeoutMs: TimeoutPresets.CRITICAL,
        });
        if (res && typeof res.access_token === "string" && res.access_token) {
            logoutEmitted = false;
            setAuthTokens(res.access_token);
            return true;
        }
        clearAuth();
        return false;
    } catch {
        // Covers the refresh endpoint's own 401 (rotated/replayed family) and
        // any network failure. Never recurses into another refresh.
        clearAuth();
        return false;
    }
}

/**
 * Single-flight refresh: concurrent callers share one in-flight attempt.
 * Clears in-memory auth on failure. Does NOT emit the logout event — the
 * caller decides (requests do, boot-time restore does not).
 */
export function refreshAccessToken(): Promise<boolean> {
    if (!refreshInFlight) {
        refreshInFlight = performRefresh().finally(() => {
            refreshInFlight = null;
        });
    }
    return refreshInFlight;
}

/**
 * Boot-time session restore: attempts a refresh from the HttpOnly cookie so
 * a reload keeps the session alive. Failure yields anonymous state (no logout
 * event — the user had no session in this page load yet).
 */
export function restoreSession(): Promise<boolean> {
    return refreshAccessToken();
}

/** Record a fresh access token after login and re-arm logout events. */
export function setAccessToken(token: string): void {
    logoutEmitted = false;
    setAuthTokens(token);
}

function isRefreshEndpoint(path: string): boolean {
    return path === AUTH_REFRESH_PATH || path === `${apiBaseUrl}${AUTH_REFRESH_PATH}`;
}

function emitLogoutOnce(): void {
    if (logoutEmitted) return;
    logoutEmitted = true;
    for (const handler of [...logoutHandlers]) {
        try {
            handler();
        } catch {
            /* handler errors must not break the request path */
        }
    }
}

/**
 * Coordinated request: on 401, trigger a single-flight refresh and retry the
 * request exactly once. If the refresh fails, in-memory auth is cleared and
 * the logout event fires once (per unauthenticated period). The refresh
 * endpoint itself is never recursed into.
 */
export async function authRequest<T>(
    path: string,
    options: RequestOptions = {},
): Promise<T> {
    try {
        return await request<T>(path, options);
    } catch (err) {
        if (err instanceof ApiError && err.status === 401 && !isRefreshEndpoint(path)) {
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                return await request<T>(path, options);
            }
            emitLogoutOnce();
        }
        throw err;
    }
}

/**
 * Coordinated HTTP method helpers (same timeout presets as the pure
 * transport, with refresh-on-401 / retry / logout semantics).
 */
export const http = {
    get: <T>(path: string, options?: RequestOptions) =>
        authRequest<T>(path, {
            timeoutMs: TimeoutPresets.NON_CRITICAL,
            ...options,
            method: "GET",
        }),
    post: <T>(path: string, options?: RequestOptions) =>
        authRequest<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "POST",
        }),
    put: <T>(path: string, options?: RequestOptions) =>
        authRequest<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "PUT",
        }),
    patch: <T>(path: string, options?: RequestOptions) =>
        authRequest<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "PATCH",
        }),
    delete: <T>(path: string, options?: RequestOptions) =>
        authRequest<T>(path, {
            timeoutMs: TimeoutPresets.CRITICAL,
            ...options,
            method: "DELETE",
        }),
};

/**
 * Test hook — resets singleton state (in-flight refresh, logout event
 * latch, handlers, in-memory token). Not part of the public surface.
 */
export function __resetAuthStateForTests(): void {
    refreshInFlight = null;
    logoutEmitted = false;
    logoutHandlers.clear();
    clearAuth();
}
