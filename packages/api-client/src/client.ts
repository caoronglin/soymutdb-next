/**
 * SoyMutDB API client — pure fetch transport.
 *
 * Reads the base URL from the VITE_API_BASE_URL environment variable, falling
 * back to "/api/v1".
 *
 * The transport is deliberately side-effect free:
 *   - the access token lives in module memory only (never persisted to
 *     localStorage/sessionStorage/URL; sessions are restored via the HttpOnly
 *     refresh cookie — see ./auth.ts)
 *   - failures are thrown as structured ApiError (status / code / request_id)
 *   - it does NOT clear auth, redirect, or refresh on 401 — the coordinating
 *     layer in ./auth.ts owns refresh-on-401, single-flight refresh, retries
 *     and logout events.
 */

/** In-memory access token (module singleton; never written to storage). */
let accessToken: string | null = null;

/**
 * Release id pinned by the current static page (Phase 3).
 *
 * When a static page is generated for release A, it sets this value so all
 * subsequent dynamic API requests keep querying release A even after the
 * active release pointer moves to B.  Sent as `X-SoyMutDB-Release` header.
 */
let releaseId: string | null = null;

/** Set the pinned release id for dynamic requests (from bootstrap data). */
export function setReleaseId(value: string | number | null | undefined): void {
    releaseId = value != null && value !== "" ? String(value) : null;
}

/** Return the currently pinned release id, if any. */
export function getReleaseId(): string | null {
    return releaseId;
}

/** Resolved API base URL. Empty env (CI unset secret) falls back to the
 * relative /api/v1 base, matching the undefined case. */
export const apiBaseUrl =
    (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.trim() || "/api/v1";

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

/** Explicit assertion required by new transport callers before they retry. */
export interface IdempotentRetryOptions {
    /** This operation is known to be idempotent and may be replayed. */
    idempotent: true;
    /** Maximum number of retry attempts (default 1). */
    maxRetries?: number;
}

/**
 * Retry a request function on transient failures, with exponential backoff.
 *
 * Retryable: timeouts (408/GATEWAY_TIMEOUT), rate limits (429), gateway errors
 * (502/503/504), and network failures (NETWORK_ERROR). New transport callers
 * must pass ``{ idempotent: true }``. The numeric form is retained unchanged
 * for public API compatibility; generic callers remain responsible for proving
 * their operation safe to replay.
 */
export async function withRetry<T>(
    fn: () => Promise<T>,
    options: number | IdempotentRetryOptions = 1,
): Promise<T> {
    const maxRetries = typeof options === "number" ? options : (options.maxRetries ?? 1);
    let lastErr: unknown;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (err) {
            lastErr = err;
            if (!isRetryableError(err) || attempt === maxRetries) throw err;
            // Exponential backoff: 500ms, 1000ms, ... (deterministic for tests).
            await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
        }
    }
    throw lastErr;
}

/** Whether an error is safe to retry (idempotent transport failure). */
function isRetryableError(err: unknown): boolean {
    if (err instanceof ApiError) {
        // Network failure surfaced as status 0 with NETWORK_ERROR code.
        if (err.code === "NETWORK_ERROR") return true;
        // Timeout, rate limit, and gateway/upstream errors.
        return [408, 429, 502, 503, 504].includes(err.status);
    }
    // Non-ApiError TypeError is typically a raw fetch network failure.
    return err instanceof TypeError;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
    /** JSON-serializable request body (for non-FormData requests). */
    json?: unknown;
    /** URL search params appended to the request URL. */
    params?: Record<string, unknown> | object;
    /** Abort timeout in milliseconds (default 30000). */
    timeoutMs?: number;
    /** Attach the in-memory Bearer token (default true). */
    auth?: boolean;
    /** Send cookies with the request via `credentials: "include"` (e.g. refresh). */
    withCredentials?: boolean;
}

/** Typed API error with status code and optional response body. */
export class ApiError extends Error {
    status: number;
    code?: string;
    details?: unknown;
    request_id?: string;

    constructor(
        message: string,
        status: number,
        code?: string,
        details?: unknown,
        request_id?: string,
    ) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.code = code;
        this.details = details;
        this.request_id = request_id;
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

/** Current in-memory access token, if any. */
export function getAccessToken(): string | null {
    return accessToken;
}

/**
 * Store the access token in module memory only.
 *
 * Never persists to localStorage/sessionStorage/URL. The refresh token is
 * delivered exclusively via the HttpOnly refresh cookie, so a `refreshToken`
 * argument (legacy callers) is accepted but ignored.
 */
export function setAuthTokens(accessTokenValue: string, _refreshToken?: string): void {
    accessToken = accessTokenValue || null;
}

/** Clear the in-memory access token. */
export function clearAuth(): void {
    accessToken = null;
}

/**
 * Execute a request and return the raw response after normalising failures.
 *
 * Keeping response handling here lets JSON and streamed file requests share the
 * same auth, release pinning, timeout, and error semantics.
 */
async function requestResponse(
    path: string,
    options: RequestOptions = {},
): Promise<Response> {
    const {
        json,
        params,
        timeoutMs = DEFAULT_TIMEOUT,
        headers,
        auth = true,
        withCredentials = false,
        ...rest
    } = options;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const requestHeaders = new Headers(headers);
    if (auth) {
        const token = getAccessToken();
        if (token) requestHeaders.set("Authorization", "Bearer " + token);
    }
    if (releaseId && !requestHeaders.has("X-SoyMutDB-Release")) {
        requestHeaders.set("X-SoyMutDB-Release", releaseId);
    }

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
            credentials: withCredentials ? "include" : rest.credentials,
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

    if (!response.ok) {
        // Unified error envelope: { error: { code, message, details? }, request_id, status_code }
        // Fall back to a flat { code, message } payload for legacy servers.
        const contentType = response.headers.get("content-type") ?? "";
        const payload = contentType.includes("application/json")
            ? await response.json().catch(() => null)
            : null;
        const envelope =
            payload && typeof payload === "object"
                ? (payload as Record<string, unknown>)
                : null;
        const errDetail =
            envelope && typeof envelope.error === "object" && envelope.error !== null
                ? (envelope.error as Record<string, unknown>)
                : null;
        const message =
            (typeof errDetail?.message === "string"
                ? errDetail.message
                : typeof envelope?.message === "string"
                  ? envelope.message
                  : null) ??
            response.statusText ??
            "Request failed";
        const code =
            (typeof errDetail?.code === "string"
                ? errDetail.code
                : typeof envelope?.code === "string"
                  ? envelope.code
                  : undefined) ?? undefined;
        const requestId =
            (typeof envelope?.request_id === "string" ? envelope.request_id : undefined) ??
            undefined;
        throw new ApiError(message, response.status, code, payload, requestId);
    }

    return response;
}

/**
 * Core JSON request function. The transport is side-effect free: auth refresh,
 * redirects, and logout handling live in ./auth.ts.
 */
export async function request<T>(
    path: string,
    options: RequestOptions = {},
): Promise<T> {
    const response = await requestResponse(path, options);
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
        ? await response.json().catch(() => null)
        : null;

    // Some endpoints (DELETE) return no content.
    if (response.status === 204 || payload === null) {
        return undefined as T;
    }
    return payload as T;
}

/** Read a successful response as a Blob for streamed file downloads. */
export async function requestBlob(
    path: string,
    options: RequestOptions = {},
): Promise<Blob> {
    return (await requestResponse(path, options)).blob();
}

/**
 * Convenience HTTP method helpers (pure transport).
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
    requestBlob,
    http,
    apiBaseUrl,
    setAuthTokens,
    clearAuth,
    getAccessToken,
    ApiError,
    TimeoutPresets,
    isTimeoutError,
    withRetry,
};
