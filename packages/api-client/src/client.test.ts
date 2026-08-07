/**
 * Tests for the core HTTP client: URL construction, params serialisation,
 * timeout handling, 401 redirect, retry logic, and error parsing.
 *
 * All tests mock `globalThis.fetch` and exercise the public API surface
 * (`request`, `http.*`, `ApiError`, `withRetry`, etc.).
 */

import {
  request,
  http,
  ApiError,
  isTimeoutError,
  withRetry,
  setAuthTokens,
  clearAuth,
  getAccessToken,
} from "./client";

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------
describe("ApiError", () => {
  it("stores status, code and details", () => {
    const err = new ApiError("nope", 404, "NOT_FOUND", { id: 1 });
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("nope");
    expect(err.status).toBe(404);
    expect(err.code).toBe("NOT_FOUND");
    expect(err.details).toEqual({ id: 1 });
  });

  it("accepts minimal constructor args", () => {
    const err = new ApiError("fail", 500);
    expect(err.status).toBe(500);
    expect(err.code).toBeUndefined();
    expect(err.details).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// isTimeoutError
// ---------------------------------------------------------------------------
describe("isTimeoutError", () => {
  it("returns true for GATEWAY_TIMEOUT ApiError", () => {
    expect(isTimeoutError(new ApiError("x", 408, "GATEWAY_TIMEOUT"))).toBe(
      true,
    );
  });

  it("returns false for other ApiError types", () => {
    expect(isTimeoutError(new ApiError("x", 500))).toBe(false);
    expect(isTimeoutError(new ApiError("x", 408))).toBe(false);
  });

  it("returns false for non-ApiError values", () => {
    expect(isTimeoutError(new Error("x"))).toBe(false);
    expect(isTimeoutError(null)).toBe(false);
    expect(isTimeoutError("string")).toBe(false);
    expect(isTimeoutError(undefined)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// withRetry
// ---------------------------------------------------------------------------
describe("withRetry", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves immediately on first success", async () => {
    const fn = vi.fn().mockResolvedValue("ok");
    await expect(withRetry(fn)).resolves.toBe("ok");
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("retries once on timeout then succeeds", async () => {
    vi.useFakeTimers();
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("to", 408, "GATEWAY_TIMEOUT"))
      .mockResolvedValueOnce("ok");

    const promise = withRetry(fn, 1);
    await vi.advanceTimersByTimeAsync(500);
    await expect(promise).resolves.toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("throws after exhausting all retries", async () => {
    // Make setTimeout fire synchronously so retries are instantaneous.
    vi.spyOn(globalThis, "setTimeout").mockImplementation(
      (fn: (...args: unknown[]) => void, _ms?: unknown, ...args: unknown[]) => {
        fn(...args);
        return 1 as unknown as NodeJS.Timeout;
      },
    );

    let callCount = 0;
    async function fn() {
      callCount++;
      throw new ApiError("to", 408, "GATEWAY_TIMEOUT");
    }

    await expect(withRetry(fn, 2)).rejects.toMatchObject({
      status: 408,
      code: "GATEWAY_TIMEOUT",
    });
    expect(callCount).toBe(3);

    vi.restoreAllMocks();
  });

  it("fails immediately on non-timeout error (no retry)", async () => {
    const err = new ApiError("server error", 500);
    const fn = vi.fn().mockRejectedValue(err);
    await expect(withRetry(fn)).rejects.toThrow(err);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// request() — URL construction, params, methods, body, response parsing
// ---------------------------------------------------------------------------
describe("request()", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // --- URL construction ---

  it("builds URL from apiBaseUrl + path", async () => {
    await request("/genes/Glyma.01G000100");
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/genes/Glyma.01G000100");
  });

  it("uses raw URL when path starts with http", async () => {
    await request("https://other.service/api/data");
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://other.service/api/data");
  });

  // --- Params serialisation ---

  it("appends query-string params", async () => {
    await request("/search", { params: { q: "soybean", page: 1 } });
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("q")).toBe("soybean");
    expect(parsed.searchParams.get("page")).toBe("1");
  });

  it("omits undefined and null params", async () => {
    await request("/test", { params: { a: 1, b: undefined, c: null } });
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("a")).toBe("1");
    expect(parsed.searchParams.has("b")).toBe(false);
    expect(parsed.searchParams.has("c")).toBe(false);
  });

  it("serialises array params with duplicate keys", async () => {
    await request("/test", { params: { ids: ["1", "2", "3"] } });
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.getAll("ids")).toEqual(["1", "2", "3"]);
  });

  it("skips query string when params is empty object", async () => {
    await request("/test", { params: {} });
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain("?");
  });

  // --- HTTP methods ---

  it("http.get uses GET", async () => {
    await http.get("/resource");
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("GET");
  });

  it("http.post uses POST and serialises JSON body", async () => {
    await http.post("/resource", { json: { name: "hello" } });
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "hello" }));
  });

  it("http.put uses PUT", async () => {
    await http.put("/resource/1");
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PUT");
  });

  it("http.patch uses PATCH", async () => {
    await http.patch("/resource/1");
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
  });

  it("http.delete uses DELETE", async () => {
    await http.delete("/resource/1");
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("DELETE");
  });

  // --- Headers ---

  it("sets Content-Type: application/json when JSON body is sent", async () => {
    await http.post("/test", { json: { k: "v" } });
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  // --- Response parsing ---

  it("parses successful JSON response", async () => {
    const result = await request<{ data: string }>("/test");
    expect(result).toEqual({ data: "ok" });
  });

  it("returns undefined for 204 No Content", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 204 }),
    );
    const result = await request("/delete");
    expect(result).toBeUndefined();
  });

  it("throws ApiError on non-ok status with error message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ message: "bad request", code: "BAD_REQ" }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(request("/bad")).rejects.toMatchObject({
      status: 400,
      code: "BAD_REQ",
      message: "bad request",
    });
  });

  it("throws ApiError with default message when JSON body lacks message field", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({}), {
        status: 502,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(request("/proxy")).rejects.toMatchObject({
      status: 502,
    });
  });

  it("parses the unified error envelope (code/message/request_id)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: { code: "token_expired", message: "Access token has expired" },
          request_id: "req-abc-123",
          status_code: 401,
        }),
        {
          status: 401,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    await expect(request("/secured")).rejects.toMatchObject({
      status: 401,
      code: "token_expired",
      message: "Access token has expired",
      request_id: "req-abc-123",
    });
  });

  it("falls back to flat code/message payloads", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ code: "BAD_REQ", message: "bad request" }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(request("/bad")).rejects.toMatchObject({
      status: 400,
      code: "BAD_REQ",
      message: "bad request",
    });
  });
});

// ---------------------------------------------------------------------------
// Timeout
// ---------------------------------------------------------------------------
describe("request timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("throws GATEWAY_TIMEOUT when fetch aborts", async () => {
    vi.useFakeTimers();

    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal as AbortSignal;
          if (signal) {
            signal.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }
        }),
    );

    const promise = request("/slow", { timeoutMs: 50 });
    vi.advanceTimersByTime(50);

    await expect(promise).rejects.toMatchObject({
      status: 408,
      code: "GATEWAY_TIMEOUT",
    });
  });

  it("throws NETWORK_ERROR when fetch fails without abort", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );
    await expect(request("/offline")).rejects.toMatchObject({
      status: 0,
      code: "NETWORK_ERROR",
    });
  });
});

// ---------------------------------------------------------------------------
// Auth header attachment
// ---------------------------------------------------------------------------
describe("auth header", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    clearAuth();
  });

  it("does not attach Authorization for anonymous requests", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await request("/public");

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });

  it("attaches Authorization from the in-memory token", async () => {
    setAuthTokens("my-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await request("/secured");

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer my-token");
  });

  it("omits Authorization when auth option is false", async () => {
    setAuthTokens("my-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await request("/public", { auth: false });

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });

  it("uses credentials include when withCredentials is set", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await request("/cookie", { withCredentials: true });

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
  });
});

// ---------------------------------------------------------------------------
// 401 handling (pure transport — no side effects)
// ---------------------------------------------------------------------------
describe("401 handling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    clearAuth();
  });

  it("throws a structured ApiError and does not clear the in-memory token", async () => {
    setAuthTokens("my-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));

    await expect(request("/secured")).rejects.toMatchObject({
      status: 401,
    });

    // The transport must not clear auth, redirect, or refresh.
    expect(getAccessToken()).toBe("my-token");
  });

  it("does not touch window.location on 401", async () => {
    const location = { href: "" };
    Object.defineProperty(globalThis, "window", {
      value: { location },
      configurable: true,
      writable: true,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));

    await expect(request("/secured")).rejects.toThrow();

    expect(location.href).toBe("");

    delete (globalThis as any).window;
  });
});
