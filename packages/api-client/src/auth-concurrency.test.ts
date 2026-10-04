/**
 * Concurrent-session coordination: a stale in-flight 401 must not fail a
 * request whose sibling already refreshed the session.
 *
 * The generation counter in `client.ts` exists to stop async auth work from
 * landing on a session it no longer belongs to. It also has to avoid the
 * opposite failure: request A starts with token T0, gets a 401, refreshes to
 * T1; request B started with T0 and gets its 401 *after* A's refresh landed.
 * B's 401 was computed against T0 and is already stale — but the session is
 * healthy, so B must retry with T1 rather than surface a 401 to the user.
 *
 * The ordering here is the real-world one (responses arrive at different
 * times). The existing "concurrent 401s share a single refresh attempt" test
 * does not reach it: with an immediately-resolving mock both 401s are handled
 * before the refresh settles, so neither is stale.
 */
import {
  authRequest,
  onAuthLogout,
  __resetAuthStateForTests,
  AUTH_REFRESH_PATH,
} from "./auth";
import { getAccessToken, setAuthTokens } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const unauthorized = () => jsonResponse({ error: { code: "unauthorized", message: "no" } }, 401);

/** Per-path attempt counter so a retry with the fresh token succeeds. */
function installFetch() {
  const attempts = new Map<string, number>();
  let openSlow = () => {};
  const slowGate = new Promise<void>((resolve) => {
    openSlow = () => resolve();
  });
  let refreshes = 0;

  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const auth = new Headers(init?.headers ?? {}).get("Authorization");
    if (url.includes(AUTH_REFRESH_PATH)) {
      refreshes += 1;
      return jsonResponse({ access_token: "token-t1", token_type: "bearer", expires_in: 900 });
    }
    if (url.endsWith("/data/slow")) {
      await slowGate;
      attempts.set(url, (attempts.get(url) ?? 0) + 1);
      return auth === "Bearer token-t0"
        ? unauthorized()
        : jsonResponse({ ok: true, seen: auth });
    }
    const seen = attempts.get(url) ?? 0;
    attempts.set(url, seen + 1);
    return seen === 0 ? unauthorized() : jsonResponse({ ok: true, seen: auth });
  });

  return { refreshCount: () => refreshes, openSlow: () => openSlow() };
}

describe("stale 401 after a sibling refresh", () => {
  beforeEach(() => {
    __resetAuthStateForTests();
    setAuthTokens("token-t0");
  });

  it("retries a late 401 with the refreshed token instead of failing", async () => {
    const { refreshCount, openSlow } = installFetch();

    const fast = authRequest("/data/fast");
    // `slow` is sent with T0; answering it only after the refresh makes its
    // 401 stale, which is the ordering a real network produces.
    const slow = authRequest("/data/slow");
    await fast;
    openSlow();

    await expect(slow).resolves.toEqual({ ok: true, seen: "Bearer token-t1" });
    expect(refreshCount()).toBe(1);
    expect(getAccessToken()).toBe("token-t1");
  });

  it("does not emit a logout for a session that is still alive", async () => {
    const onLogout = vi.fn();
    onAuthLogout(onLogout);
    const { openSlow } = installFetch();
    const fast = authRequest("/data/fast");
    const slow = authRequest("/data/slow");
    await fast;
    openSlow();
    await slow.catch(() => undefined);
    expect(onLogout).not.toHaveBeenCalled();
  });

  it("still refuses to replay an unsafe method", async () => {
    const { openSlow } = installFetch();
    const first = authRequest("/data/fast", { method: "POST" });
    const second = authRequest("/data/slow", { method: "POST" });
    await first.catch(() => undefined);
    openSlow();
    // Both unsafe requests saw a 401 computed against T0. Neither may be
    // replayed automatically (H-06), so the stale one still surfaces.
    await expect(second).rejects.toMatchObject({ status: 401 });
  });
});