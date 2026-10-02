/**
 * Tests for the auth coordination layer: refresh-on-401 with single-flight,
 * retry-once semantics, logout events, session restore, legacy cleanup and
 * refresh endpoint guard rails.
 *
 * All tests mock `globalThis.fetch` and exercise the public surface of
 * ./auth plus the token accessor from ./client.
 */
import {
  authRequest,
  http,
  restoreSession,
  refreshAccessToken,
  onAuthLogout,
  clearLegacyTokens,
  setAccessToken,
  __resetAuthStateForTests,
  AUTH_REFRESH_PATH,
  getCurrentUser,
} from "./auth";
import { getAccessToken, setAuthTokens, clearAuth, ApiError } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Stateful fetch mock.
 *
 * - calls to the refresh endpoint return `refreshResponse` (once per call)
 * - all other calls return 200 for the first `failures` attempts of each
 *   path (per path), then `okBody` afterwards.
 */
function installFetchMock(opts: {
  refreshResponse: () => Response;
  failures?: number;
  okBody?: unknown;
}) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const perPath = new Map<string, number>();

  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init: init ?? {} });
      if (url.includes(AUTH_REFRESH_PATH)) {
        return opts.refreshResponse();
      }
      const failures = opts.failures ?? 0;
      const count = perPath.get(url) ?? 0;
      perPath.set(url, count + 1);
      if (count < failures) {
        return jsonResponse(
          { error: { code: "unauthorized", message: "Unauthorized" }, request_id: "r1" },
          401,
        );
      }
      return jsonResponse(opts.okBody ?? { ok: true });
    },
  );

  return {
    calls,
    refreshCalls: () => calls.filter((c) => c.url.includes(AUTH_REFRESH_PATH)),
  };
}

function lastInitFor(calls: Array<{ url: string; init: RequestInit }>, url: string) {
  const match = [...calls].reverse().find((c) => c.url === url);
  return match?.init ?? null;
}

describe("auth coordination", () => {
  beforeEach(() => {
    __resetAuthStateForTests();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    __resetAuthStateForTests();
  });

  it("401 → single refresh → retries once with the new token", async () => {
    const { calls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
      okBody: { data: "ok" },
    });

    const result = await authRequest<{ data: string }>("/secured");

    expect(result).toEqual({ data: "ok" });
    // 1 original 401 + 1 refresh + 1 retry = 3 calls.
    expect(calls).toHaveLength(3);
    expect(calls.filter((c) => c.url.includes(AUTH_REFRESH_PATH))).toHaveLength(1);

    const retryInit = lastInitFor(calls, "/api/v1/secured");
    const retryHeaders = retryInit?.headers as Headers | undefined;
    expect(retryHeaders?.get("Authorization")).toBe("Bearer fresh-token");
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("replays an idempotent PUT once after a successful refresh", async () => {
    const { calls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
      okBody: { saved: true },
    });

    await expect(authRequest("/settings/site", { method: "PUT", json: { title: "SoyMutDB" } })).resolves.toEqual({
      saved: true,
    });
    expect(calls.filter((call) => call.url === "/api/v1/settings/site")).toHaveLength(2);
  });

  it("does not replay a POST after a successful refresh", async () => {
    const { calls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
    });

    await expect(authRequest("/imports", { method: "POST", json: { source: "upload" } })).rejects.toMatchObject({
      status: 401,
    });
    expect(calls.filter((call) => call.url === "/api/v1/imports")).toHaveLength(1);
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("refresh request carries credentials:include and no body", async () => {
    const { refreshCalls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
    });

    await authRequest("/secured");

    const [refreshCall] = refreshCalls();
    expect(refreshCall.init.credentials).toBe("include");
    expect(refreshCall.init.body).toBeUndefined();
    expect(refreshCall.init.method).toBe("POST");
  });

  it("concurrent 401s share a single refresh attempt", async () => {
    const { refreshCalls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
      okBody: { ok: true },
    });

    const [a, b] = await Promise.all([
      authRequest("/data/a"),
      authRequest("/data/b"),
    ]);

    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(refreshCalls()).toHaveLength(1);
  });

  it("refresh failure clears memory and emits logout exactly once", async () => {
    setAuthTokens("stale-token");
    const onLogout = vi.fn();
    onAuthLogout(onLogout);

    installFetchMock({
      refreshResponse: () =>
        jsonResponse({ error: { code: "invalid_token", message: "nope" }, request_id: "r2" }, 401),
      failures: 1,
    });

    await expect(authRequest("/secured")).rejects.toMatchObject({ status: 401 });
    expect(onLogout).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();

    // A second failure in the same unauthenticated period must not re-emit.
    await expect(authRequest("/secured2")).rejects.toMatchObject({ status: 401 });
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("logout event re-arms after a successful refresh", async () => {
    const onLogout = vi.fn();
    onAuthLogout(onLogout);

    // A session must exist for a refresh failure to be a logout — otherwise
    // this is an anonymous 401, which stays silent (see the dedicated test
    // below).
    setAccessToken("token-before-failure");

    // First failure → logout fires.
    installFetchMock({
      refreshResponse: () =>
        jsonResponse({ error: { code: "invalid_token", message: "nope" }, request_id: "r2" }, 401),
      failures: 1,
    });
    await expect(authRequest("/a")).rejects.toMatchObject({ status: 401 });
    expect(onLogout).toHaveBeenCalledTimes(1);

    // Restore only the fetch spy — vi.restoreAllMocks() would wipe the
    // onLogout spy's call history.
    vi.mocked(globalThis.fetch).mockRestore();

    // New session via login → re-armed.
    setAccessToken("new-token");

    // Second failure now fires again.
    installFetchMock({
      refreshResponse: () =>
        jsonResponse({ error: { code: "invalid_token", message: "nope" }, request_id: "r3" }, 401),
      failures: 1,
    });
    await expect(authRequest("/b")).rejects.toMatchObject({ status: 401 });
    expect(onLogout).toHaveBeenCalledTimes(2);
  });

  it("refresh endpoint 401 does not recurse into another refresh", async () => {
    const { refreshCalls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ error: { code: "invalid_token", message: "nope" }, request_id: "r4" }, 401),
    });

    await expect(authRequest(AUTH_REFRESH_PATH)).rejects.toMatchObject({ status: 401 });
    // Only the refresh call itself — no retry loop, no second refresh.
    expect(refreshCalls()).toHaveLength(1);
  });

  it("anonymous 401 does not emit a logout event", async () => {
    // The portal renders published routes to visitors with no session; a
    // public page that reads GET /auth/me (or any per-account endpoint) gets
    // 401 by design. Emitting logout there navigates the visitor to /login
    // and takes /blast, /analyses, ... offline for anonymous readers.
    expect(getAccessToken()).toBeNull();
    const onLogout = vi.fn();
    onAuthLogout(onLogout);

    const { refreshCalls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ error: { code: "invalid_token", message: "nope" }, request_id: "r5" }, 401),
      failures: 1,
    });

    await expect(authRequest("/auth/me")).rejects.toMatchObject({ status: 401 });

    expect(onLogout).not.toHaveBeenCalled();
    // The refresh was still attempted exactly once, so a cookie-backed
    // session on a freshly loaded page is picked up.
    expect(refreshCalls()).toHaveLength(1);
  });

  it("coordinated http helpers route through authRequest", async () => {
    const { calls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "fresh-token", token_type: "bearer", expires_in: 900 }),
      failures: 1,
    });

    await http.get("/resource");

    expect(calls).toHaveLength(3);
    expect(calls[0].init.method).toBe("GET");
  });

  it("downloads a Blob through the authenticated transport", async () => {
    setAccessToken("download-token");
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        calls.push({ url: String(input), init: init ?? {} });
        return new Response("timestamp,action\n2026-01-01,login\n", {
          status: 200,
          headers: { "content-type": "text/csv" },
        });
      },
    );

    const result = await http.download("/admin/audit-logs/export");

    expect(result).toBeInstanceOf(Blob);
    await expect(result.text()).resolves.toContain("timestamp,action");
    expect(calls).toHaveLength(1);
    expect(calls[0].init.method).toBe("GET");
    expect((calls[0].init.headers as Headers).get("Authorization")).toBe(
      "Bearer download-token",
    );
  });

  it("restoreSession restores the token from the refresh cookie", async () => {
    installFetchMock({
      refreshResponse: () =>
        jsonResponse({ access_token: "cookie-token", token_type: "bearer", expires_in: 900 }),
    });

    const ok = await restoreSession();

    expect(ok).toBe(true);
    expect(getAccessToken()).toBe("cookie-token");
  });

  it("restoreSession failure yields anonymous state without logout event", async () => {
    const onLogout = vi.fn();
    onAuthLogout(onLogout);

    installFetchMock({
      refreshResponse: () => jsonResponse({}, 401),
    });

    const ok = await restoreSession();

    expect(ok).toBe(false);
    expect(getAccessToken()).toBeNull();
    expect(onLogout).not.toHaveBeenCalled();
  });

  it("anonymous request carries no Authorization header", async () => {
    const { calls } = installFetchMock({ refreshResponse: () => jsonResponse({}, 401) });

    await authRequest("/public");

    const init = lastInitFor(calls, "/api/v1/public");
    const headers = init?.headers as Headers | undefined;
    expect(headers?.has("Authorization")).toBe(false);
  });

  it("clearLegacyTokens removes legacy keys from both storages", () => {
    const ls: Record<string, string> = {};
    const ss: Record<string, string> = {};
    Object.defineProperty(globalThis, "localStorage", {
      value: {
        getItem: (k: string) => ls[k] ?? null,
        setItem: (k: string, v: string) => {
          ls[k] = v;
        },
        removeItem: (k: string) => {
          delete ls[k];
        },
        clear: () => {
          for (const k of Object.keys(ls)) delete ls[k];
        },
        length: 0,
        key: () => null,
      },
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "sessionStorage", {
      value: {
        getItem: (k: string) => ss[k] ?? null,
        setItem: (k: string, v: string) => {
          ss[k] = v;
        },
        removeItem: (k: string) => {
          delete ss[k];
        },
        clear: () => {
          for (const k of Object.keys(ss)) delete ss[k];
        },
        length: 0,
        key: () => null,
      },
      configurable: true,
      writable: true,
    });

    ls["soymutdb_token"] = "legacy-access";
    ls["soymutdb_refresh_token"] = "legacy-refresh";
    ls["soymutdb_access_token"] = "legacy-alt";
    ss["soymutdb_token"] = "legacy-access";
    ss["soymutdb_refresh_token"] = "legacy-refresh";

    clearLegacyTokens();

    expect(ls["soymutdb_token"]).toBeUndefined();
    expect(ls["soymutdb_refresh_token"]).toBeUndefined();
    expect(ls["soymutdb_access_token"]).toBeUndefined();
    expect(ss["soymutdb_token"]).toBeUndefined();
    expect(ss["soymutdb_refresh_token"]).toBeUndefined();

    delete (globalThis as any).localStorage;
    delete (globalThis as any).sessionStorage;
  });

  it("setAuthTokens stores in memory only (never persisted)", () => {
    const ls: Record<string, string> = {};
    Object.defineProperty(globalThis, "localStorage", {
      value: {
        getItem: (k: string) => ls[k] ?? null,
        setItem: (k: string, v: string) => {
          ls[k] = v;
        },
        removeItem: (k: string) => {
          delete ls[k];
        },
        clear: () => {
          for (const k of Object.keys(ls)) delete ls[k];
        },
        length: 0,
        key: () => null,
      },
      configurable: true,
      writable: true,
    });

    setAuthTokens("mem-token", "ignored-refresh-token");

    expect(getAccessToken()).toBe("mem-token");
    expect(Object.keys(ls)).toHaveLength(0);

    clearAuth();
    expect(getAccessToken()).toBeNull();
    expect(Object.keys(ls)).toHaveLength(0);

    delete (globalThis as any).localStorage;
  });

  it("refreshAccessToken returns false on network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const ok = await refreshAccessToken();

    expect(ok).toBe(false);
    expect(getAccessToken()).toBeNull();
  });

  it("errors never expose tokens in the message", async () => {    setAuthTokens("secret-token");
    installFetchMock({
      refreshResponse: () =>
        jsonResponse(
          { error: { code: "invalid_token", message: "invalid token" }, request_id: "r5" },
          401,
        ),
      failures: 1,
    });

    try {
      await authRequest("/secured");
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.message).not.toContain("secret-token");
      expect(JSON.stringify(apiErr.details)).not.toContain("secret-token");
      // The original 401 propagates to the caller (refresh failure does not
      // replace it), so the correlation id is the original request's.
      expect(apiErr.request_id).toBe("r1");
    }
  });
});

describe("getCurrentUser", () => {
  beforeEach(() => {
    __resetAuthStateForTests();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    __resetAuthStateForTests();
  });

  it("parses the profile from GET /auth/me and carries the bearer token", async () => {
    setAccessToken("access-token");
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        calls.push({ url: String(input), init: init ?? {} });
        return jsonResponse({
          id: "u1",
          username: "rui",
          email: "rui@example.org",
          full_name: null,
          is_active: true,
          is_superuser: false,
          role_name: "researcher",
        });
      },
    );

    const user = await getCurrentUser();

    expect(user.role_name).toBe("researcher");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/v1/auth/me");
    expect(calls[0].init.method).toBe("GET");
    expect((calls[0].init.headers as Headers).get("Authorization")).toBe(
      "Bearer access-token",
    );
  });

  it("rejects with the 401 for an anonymous session after one refresh attempt", async () => {
    const { refreshCalls } = installFetchMock({
      refreshResponse: () =>
        jsonResponse(
          { error: { code: "invalid_token", message: "nope" }, request_id: "r1" },
          401,
        ),
      failures: 1,
    });

    await expect(getCurrentUser()).rejects.toMatchObject({ status: 401 });
    // One refresh attempt is made (the token may simply be expired), then the
    // original 401 propagates so the caller can treat it as anonymous.
    expect(refreshCalls()).toHaveLength(1);
  });
});
