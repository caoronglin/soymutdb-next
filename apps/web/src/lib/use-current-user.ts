/**
 * Current-user auth hook — resolves the session role for route guards.
 *
 * The public portal has no hard dependency on being logged in, so
 * `GET /auth/me` failing (401 / network) is treated as "anonymous" rather
 * than an error: the analyses module then shows the researcher-required
 * empty state instead of hiding the routes.
 */

import { useQuery } from "@tanstack/react-query";
import { secureHttp } from "./api";

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  /** e.g. "viewer" | "researcher" | "administrator" (null for legacy rows). */
  role_name?: string | null;
}

/** Roles that satisfy the analyses "researcher+" requirement. */
const RESEARCHER_ROLES = new Set(["researcher", "administrator"]);

/** Fetch the current user; `null` when anonymous / unauthenticated. */
export function fetchCurrentUser(): Promise<CurrentUser | null> {
  return secureHttp
    .get<CurrentUser>("/auth/me")
    .then((user) => user ?? null)
    .catch(() => null);
}

/** Current user (or null when anonymous). Cached 60s, no retry — the guard degrades to "no access" on failure. */
export function useCurrentUser(): {
  user: CurrentUser | null;
  isLoading: boolean;
} {
  const query = useQuery({
    queryKey: ["current-user"],
    queryFn: fetchCurrentUser,
    staleTime: 60_000,
    retry: false,
  });
  return { user: query.data ?? null, isLoading: query.isLoading };
}

/** True when the current session may run analyses (researcher or higher). */
export function useIsResearcher(): { isResearcher: boolean; isLoading: boolean } {
  const { user, isLoading } = useCurrentUser();
  const isResearcher = user
    ? user.is_superuser || RESEARCHER_ROLES.has(user.role_name ?? "")
    : false;
  return { isResearcher, isLoading };
}
