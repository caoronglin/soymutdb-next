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
const restoreAttempted = ref(false);

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
  }

  async function restore(): Promise<void> {
    if (restoreAttempted.value) return;
    restoreAttempted.value = true;
    try {
      // `restoreSession` exchanges the HttpOnly refresh cookie for a fresh
      // access token and reports whether that succeeded. The console never sees
      // the refresh token itself.
      const restored = await restoreSession();
      isAuthenticated.value = restored;
      if (restored) username.value = "administrator";
    } catch {
      // A console with no restorable session is simply signed out.
      isAuthenticated.value = false;
    }
  }

  function logout(): void {
    clearAuth();
    isAuthenticated.value = false;
    username.value = null;
  }

  return {
    isAuthenticated: computed(() => isAuthenticated.value),
    username: computed(() => username.value),
    login,
    logout,
    restore,
  };
}
