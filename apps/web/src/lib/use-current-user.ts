/**
 * Current-user auth hook — resolves the session role for route guards.
 *
 * The public portal has no hard dependency on being logged in, so the read is
 * gated on the session state machine (`lib/session.ts`): an anonymous visitor
 * must issue **zero** personal requests, and a transport failure must not be
 * reported as "not allowed".
 *
 * Before this gating the probe ran unconditionally on every page
 * (`GET /auth/me` -> 401 -> refresh -> 401), which is regression K-1.
 */

import { useQuery } from "@tanstack/react-query";
import { secureHttp } from "./api";
import { useSession } from "./session-context";
import type { SessionStatus } from "./session";

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  /** e.g. "viewer" | "researcher" | "administrator" (null for legacy rows). */
  role_name?: string | null;
  /**
   * The roles this session actually satisfies, from `GET /auth/me`
   * (`effective_roles`, expanded server-side from `_ROLE_GRANTS`).
   *
   * Authorisation is read from here, never from a private copy of the role
   * table: that copy is what made the portal deny curator, content_editor,
   * auditor and four other roles a capability `require_role(RESEARCHER)`
   * already grants them. Absent means "the server did not say", which is not
   * the same as "no grants" — see `useIsResearcher`.
   */
  effective_roles?: string[];
}

/**
 * The only role that does **not** satisfy `require_role(RoleName.RESEARCHER)`.
 *
 * Kept next to `grantsResearcher` because that function's fallback for an API
 * predating `effective_roles` is exactly "any role except this one" — the
 * shape of `apps/api/app/core/security.py::_ROLE_GRANTS`, where `viewer`
 * grants only itself and every other role grants `researcher` (audit D-05).
 * The authoritative answer is the server's; this is the degraded path.
 */
const VIEWER_ONLY = "viewer";

/** True when the server reported the session may run analyses. */
export function grantsResearcher(user: CurrentUser): boolean {
  if (user.is_superuser) return true;
  if (Array.isArray(user.effective_roles)) {
    return user.effective_roles.includes("researcher");
  }
  // A deployment whose API predates `effective_roles` says nothing here.
  // Falling back to "not a viewer" reproduces the grant table's shape for the
  // roles that existed then, and fails closed for a viewer.
  const role = user.role_name ?? null;
  return role !== null && role !== VIEWER_ONLY;
}

export interface CurrentUserState {
  user: CurrentUser | null;
  isLoading: boolean;
  /** The session status the gate decided on; `error` is not a permission answer. */
  status: SessionStatus;
}

/**
 * Fetch the current user.
 *
 * Throws on 401/403 so the caller can tell "not signed in" from a broken
 * network; the query is disabled while no session exists, so in practice this
 * only runs for an authenticated visitor.
 */
export function fetchCurrentUser(): Promise<CurrentUser | null> {
  return secureHttp
    .get<CurrentUser>("/auth/me")
    .then((user) => user ?? null);
}
export function useCurrentUser(): CurrentUserState {
  const session = useSession();
  const query = useQuery({
    queryKey: ["current-user", session.sessionId],
    queryFn: fetchCurrentUser,
    enabled: session.canQueryPersonal,
    staleTime: 60_000,
    retry: false,
  });
  return {
    user: session.canQueryPersonal ? (query.data ?? null) : null,
    isLoading: session.status === "restoring" || query.isLoading,
    status: session.status,
  };
}

/**
 * True when the *server* may run analyses for this session.
 *
 * The backend decides: `apps/api/app/core/security.py` grants the
 * `researcher` capability to curator, data_manager, track_manager,
 * blast_manager, seed_manager, content_editor, auditor and administrator, not
 * only to the two role names a front-end list would contain. Until a
 * user-capability endpoint exists, this reports the server's own answer from
 * `/auth/me` rather than a second, divergent role table.
 */
/**
 * True when the *server* may run analyses for this session.
 *
 * Backed by `GET /auth/me`'s `effective_roles`; the API remains the authority
 * and returns its own 403 regardless of what the client concludes.
 */
export function useIsResearcher(): { isResearcher: boolean; isLoading: boolean } {
  const { user, isLoading } = useCurrentUser();
  const isResearcher = user ? grantsResearcher(user) : false;
  return { isResearcher, isLoading };
}