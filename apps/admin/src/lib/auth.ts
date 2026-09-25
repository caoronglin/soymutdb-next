/**
 * Administrator session.
 *
 * The access token lives in module memory only (never storage): a stolen
 * localStorage token survives an XSS that an in-memory token also would, but it
 * survives a browser restart and a shared machine, which the memory-only token
 * does not. The refresh token stays in an HttpOnly cookie the console never
 * reads, and `restoreSession` is what turns it back into an access token on
 * reload.
 */
import { computed, ref } from "vue";

import { authRequest, clearAuth, restoreSession, setAccessToken } from "@soymutdb/api-client";

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

const isAuthenticated = ref(false);
const username = ref<string | null>(null);

/**
 * The in-flight restore, shared by every caller.
 *
 * A plain "already tried" flag is not enough: the router guard and the app's
 * mount both call `restore()`, and whichever runs first marks the attempt done
 * while the refresh is still in the air — so the second caller reads
 * `isAuthenticated === false` and bounces a signed-in operator back to the login
 * page on every reload. Handing out the same promise makes both callers wait for
 * the same answer.
 */
let restorePromise: Promise<boolean> | null = null;

/** Decode the token's `sub` without verifying it — the API already did. */
function subjectOf(token: string): string | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof decoded?.sub === "string" ? decoded.sub : null;
  } catch {
    return null;
  }
}

export function useAuth() {
  async function login(identifier: string, password: string): Promise<void> {
    const response = await authRequest<LoginResponse>("/auth/login", {
      method: "POST",
      json: { username: identifier, password },
    });
    setAccessToken(response.access_token);
    username.value = subjectOf(response.access_token) ?? identifier;
    isAuthenticated.value = true;
    // Drop any restore that already failed (a signed-out boot has none, but a
    // reload that raced the login does): a cached "no session" would bounce the
    // operator straight back to the login page after a successful sign-in.
    restorePromise = null;
  }

  async function restore(): Promise<boolean> {
    restorePromise ??= (async () => {
      try {
        // `restoreSession` exchanges the HttpOnly refresh cookie for a fresh
        // access token and reports whether that succeeded. The console never
        // sees the refresh token itself.
        return await restoreSession();
      } catch {
        // A console with no restorable session is simply signed out.
        return false;
      }
    })();
    const restored = await restorePromise;
    isAuthenticated.value = restored;
    if (restored && !username.value) username.value = "administrator";
    return restored;
  }

  function logout(): void {
    clearAuth();
    isAuthenticated.value = false;
    username.value = null;
    // A later sign-in must be able to restore again.
    restorePromise = null;
  }

  return {
    isAuthenticated: computed(() => isAuthenticated.value),
    username: computed(() => username.value),
    login,
    logout,
    restore,
  };
}
