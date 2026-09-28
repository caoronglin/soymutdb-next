/**
 * Current-user auth composable — resolves the session role for route guards.
 *
 * The public portal has no hard dependency on being logged in, so a failing
 * `GET /auth/me` (401 / network) is treated as "anonymous" rather than an
 * error: the analyses module then shows the researcher-required empty state
 * instead of hiding the routes.
 *
 * The probe only runs once a session is known to exist. `GET /auth/me` goes
 * through the auth-aware transport, which treats an unrefreshable 401 as
 * "the session died" and fires the global logout handler — and `main.ts`
 * redirects that to `/login`. Probing while anonymous would therefore bounce
 * every public page to the sign-in screen, which is exactly what happened when
 * the notification bell started mounting this composable in the shared header.
 * Anonymous visitors now skip the probe entirely; `main.ts` enables it after
 * `restoreSession()` succeeds, and the login form enables it on success.
 *
 * This guard is UX only — the authorization boundary is the server's
 * `require_role(RESEARCHER)` dependency, never this client-side check.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, type ComputedRef } from "vue";

import { getCurrentUser, type CurrentUser } from "@soymutdb/api-client";

export type { CurrentUser };

/**
 * Whether this page load has an authenticated session.
 *
 * Module state, not component state: the header, the route guards and the
 * notification bell must all agree, and a second probe would double the
 * logout-emission risk above.
 */
const sessionEstablished = ref(false);

/** Record the boot-time session probe result (see `main.ts`). */
export function markSessionEstablished(value: boolean): void {
  sessionEstablished.value = value;
}

/** Test seam: reset the module state between cases. */
export function __resetSessionStateForTests(): void {
  sessionEstablished.value = false;
}

/**
 * Whether an assigned role grants the server's RESEARCHER grant.
 *
 * Derived from the server authorization table in
 * `apps/api/app/core/security.py` (`_ROLE_GRANTS`, lines ~141-160): every role
 * except `viewer` includes `researcher` in its grant set, and `administrator`
 * grants every role. `is_superuser` bypasses the table entirely.
 *
 * Deliberately broader than the React baseline, which only accepted
 * `{researcher, administrator}` and therefore wrongly denied curator /
 * data_manager / track_manager / blast_manager / seed_manager / content_editor
 * / auditor — all of whom the server does let submit analyses. Over-admission
 * is harmless here (the server re-checks); over-denial is a real defect.
 */
export function isResearcher(user: CurrentUser | null): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  return user.role_name != null && user.role_name !== "viewer";
}

export interface UseCurrentUserResult {
  user: ComputedRef<CurrentUser | null>;
  isResearcher: ComputedRef<boolean>;
  isLoading: ComputedRef<boolean>;
}

/**
 * Current user (or `null` when anonymous), plus the researcher verdict.
 *
 * The query resolves to `null` on any failure — it never enters an error state
 * and never triggers a redirect loop. Cached 60s, no retry: a guard degrades
 * to "no access" instead of stalling on the default backoff.
 */
export function useCurrentUser(): UseCurrentUserResult {
  const query = useQuery({
    queryKey: ["current-user"],
    queryFn: async (): Promise<CurrentUser | null> => {
      try {
        return await getCurrentUser();
      } catch {
        // 401 (after the transport's one refresh attempt), network failure, or
        // an unparseable body all mean the same thing to a guard: anonymous.
        return null;
      }
    },
    // Anonymous visitors must never send this probe: the transport would treat
    // the 401 as a dead session and redirect them to /login.
    enabled: computed(() => sessionEstablished.value),
    staleTime: 60_000,
    retry: false,
  });

  const user = computed<CurrentUser | null>(() => toValue(query.data) ?? null);
  return {
    user,
    isResearcher: computed(() => isResearcher(user.value)),
    isLoading: computed(() => toValue(query.isLoading)),
  };
}
