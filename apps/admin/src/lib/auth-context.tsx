import * as React from "react";
import {
  http,
  getAccessToken,
  setAccessToken,
  clearAuth,
  restoreSession,
  onAuthLogout,
} from "@soymutdb/api-client";

/** Authenticated admin user. */
export interface AuthUser {
  username: string;
}

/**
 * Shape of the `POST /auth/login` response. The refresh token is delivered
 * exclusively via the HttpOnly refresh cookie and never appears in JSON.
 */
interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/** Value exposed by the auth context. */
export interface AuthContextValue {
  /** True while the initial refresh-cookie session restore is pending. */
  isRestoringSession: boolean;
  isAuthenticated: boolean;
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

/** Decode the payload segment of a JWT into a plain object. */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Extract a username from a JWT payload (`username` or `sub` claim). */
function usernameFromToken(token: string): string | null {
  const payload = decodeJwtPayload(token);
  if (!payload) return null;
  const username = payload["username"];
  if (typeof username === "string" && username) return username;
  const sub = payload["sub"];
  if (typeof sub === "string" && sub) return sub;
  return null;
}

/**
 * Auth provider: restores a session from the HttpOnly refresh cookie on
 * mount, exposes login/logout and the current authentication state.
 *
 * AuthProvider sits outside the router, so logout navigates via
 * `window.location` (full reload) rather than the router. The shared
 * transport owns the access token (module memory only) and fires the logout
 * event when a mid-session refresh fails — this provider listens and drops
 * back to the login screen.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isRestoringSession, setIsRestoringSession] = React.useState(true);
  const [isAuthenticated, setIsAuthenticated] = React.useState<boolean>(false);
  const [user, setUser] = React.useState<AuthUser | null>(null);

  // Restore a session from the HttpOnly refresh cookie (single-flight with
  // any in-flight refresh triggered by requests). Failure → anonymous state.
  React.useEffect(() => {
    let cancelled = false;
    void restoreSession()
      .then((ok) => {
        if (cancelled || !ok) return;
        const token = getAccessToken();
        const username = token ? usernameFromToken(token) : null;
        setIsAuthenticated(true);
        setUser(username ? { username } : null);
      })
      .finally(() => {
        if (!cancelled) setIsRestoringSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Hard session death (refresh failed while handling a 401) → login page.
  React.useEffect(
    () =>
      onAuthLogout(() => {
        setIsAuthenticated(false);
        setUser(null);
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
      }),
    [],
  );

  const login = React.useCallback(
    async (username: string, password: string): Promise<AuthUser> => {
      const res = await http.post<LoginResponse>("/auth/login", {
        json: { username, password },
      });
      setAccessToken(res.access_token);
      const resolved = usernameFromToken(res.access_token) ?? username;
      const authedUser: AuthUser = { username: resolved };
      setIsAuthenticated(true);
      setUser(authedUser);
      return authedUser;
    },
    [],
  );

  const logout = React.useCallback(() => {
    // Best-effort server-side family revocation (clears the refresh cookie).
    void http
      .post("/auth/logout", { withCredentials: true })
      .catch(() => {
        /* local logout proceeds regardless */
      });
    clearAuth();
    setIsAuthenticated(false);
    setUser(null);
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({ isRestoringSession, isAuthenticated, user, login, logout }),
    [isRestoringSession, isAuthenticated, user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Access the auth context. Throws if used outside an `AuthProvider`. */
export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

export default AuthProvider;
