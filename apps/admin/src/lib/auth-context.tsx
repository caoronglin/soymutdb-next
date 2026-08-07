import * as React from "react";
import { http, setAuthTokens, clearAuth } from "@soymutdb/api-client";

/** localStorage key used by the API client to persist the access token. */
const TOKEN_KEY = "soymutdb_token";

/** Authenticated admin user. */
export interface AuthUser {
  username: string;
}

/** Shape of the `POST /auth/login` response. */
interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** Value exposed by the auth context. */
export interface AuthContextValue {
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
 * Auth provider: checks for a stored JWT on mount, exposes login/logout and
 * the current authentication state. AuthProvider sits outside the router, so
 * logout navigates via `window.location` (full reload) rather than the router.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = React.useState<boolean>(() => {
    if (typeof localStorage === "undefined") return false;
    return localStorage.getItem(TOKEN_KEY) !== null;
  });

  const [user, setUser] = React.useState<AuthUser | null>(() => {
    if (typeof localStorage === "undefined") return null;
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return null;
    const username = usernameFromToken(token);
    return username ? { username } : null;
  });

  const login = React.useCallback(
    async (username: string, password: string): Promise<AuthUser> => {
      const res = await http.post<LoginResponse>("/auth/login", {
        json: { username, password },
      });
      setAuthTokens(res.access_token, res.refresh_token);
      const resolved = usernameFromToken(res.access_token) ?? username;
      const authedUser: AuthUser = { username: resolved };
      setIsAuthenticated(true);
      setUser(authedUser);
      return authedUser;
    },
    [],
  );

  const logout = React.useCallback(() => {
    clearAuth();
    setIsAuthenticated(false);
    setUser(null);
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({ isAuthenticated, user, login, logout }),
    [isAuthenticated, user, login, logout],
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
