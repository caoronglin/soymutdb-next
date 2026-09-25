import { beforeEach, describe, expect, it, vi } from "vitest";

// The session lives in module memory, so this suite reads the module's public
// behaviour rather than a DOM: what matters is that a successful login marks the
// session, a failure does not, and signing out clears it.
vi.mock("@soymutdb/api-client", () => ({
  authRequest: vi.fn(),
  clearAuth: vi.fn(),
  restoreSession: vi.fn(),
  setAccessToken: vi.fn(),
}));

import { authRequest, clearAuth, restoreSession, setAccessToken } from "@soymutdb/api-client";
import { useAuth } from "./auth";

const token = `header.${btoa(JSON.stringify({ sub: "admin@example.org" }))}.signature`;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("admin session", () => {
  it("records the session from the access token after a successful login", async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: token, token_type: "bearer", expires_in: 900 });
    const auth = useAuth();

    await auth.login("admin@example.org", "secret");

    expect(setAccessToken).toHaveBeenCalledWith(token);
    expect(auth.isAuthenticated.value).toBe(true);
    expect(auth.username.value).toBe("admin@example.org");
  });

  it("does not grant a session when the API rejects the credentials", async () => {
    vi.mocked(authRequest).mockRejectedValue(new Error("401"));
    const auth = useAuth();
    // The session is module state shared by every caller, so start from the
    // signed-out state a fresh console has.
    auth.logout();
    vi.mocked(setAccessToken).mockClear();

    await expect(auth.login("admin@example.org", "wrong")).rejects.toThrow();

    expect(setAccessToken).not.toHaveBeenCalled();
    expect(auth.isAuthenticated.value).toBe(false);
  });

  it("restores a session from the refresh cookie at most once", async () => {
    vi.mocked(restoreSession).mockResolvedValue(true);
    const auth = useAuth();

    await auth.restore();
    await auth.restore();

    expect(restoreSession).toHaveBeenCalledTimes(1);
    expect(auth.isAuthenticated.value).toBe(true);
  });

  it("clears the session on sign out", async () => {
    vi.mocked(restoreSession).mockResolvedValue(true);
    const auth = useAuth();
    await auth.restore();

    auth.logout();

    expect(clearAuth).toHaveBeenCalled();
    expect(auth.isAuthenticated.value).toBe(false);
    expect(auth.username.value).toBeNull();
  });
});
