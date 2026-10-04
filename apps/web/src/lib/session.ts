/**
 * Portal session state machine (pure).
 *
 * Review outcome for the previous `session.ts`: it gated probes with a
 * module-level boolean and classified every failure as `anonymous` or
 * `expired`. Two defects followed from that, both recorded in the audited plan:
 *
 * - a plain boolean is not reactive, so flipping it could not re-render any
 *   consumer (H-08: an unwired gate must not be reported as a fix);
 * - `classifyAuthProbe` mapped a network failure and a 5xx to the same outcome
 *   as a 401, which is exactly the "network failure looks like no permission"
 *   confusion the plan forbids (D-04).
 *
 * This module owns only the transitions. React lives in `session-context.tsx`
 * and the transport stays in `packages/api-client/src/auth.ts`.
 */
import { ApiError } from "@soymutdb/api-client";

export type SessionStatus =
  /** A boot refresh is in flight; public pages stay readable, gated actions wait. */
  | "restoring"
  /** No session in this tab. Personal reads must not be issued. */
  | "anonymous"
  /** A session exists; personal reads may run. */
  | "authenticated"
  /** A session existed and is gone. Offer re-authentication, do not force it. */
  | "expired"
  /** The refresh could not be completed. Retryable, and not an auth verdict. */
  | "error";

export interface SessionSnapshot {
  status: SessionStatus;
  /**
   * Whether `/auth/me`, notifications and personal task lists may run.
   * False for restoring, anonymous, expired and error: an unknown or broken
   * session must not be answered with a personal request.
   */
  canQueryPersonal: boolean;
  /** Whether account-gated actions may be offered to the visitor. */
  canAct: boolean;
  /** Present only for `error`, so the UI can offer a retry. */
  error?: unknown;
  /** Increments on every authenticated transition; keys personal caches. */
  sessionId: number;
}

export const INITIAL_SESSION: SessionSnapshot = {
  status: "restoring",
  canQueryPersonal: false,
  canAct: false,
  sessionId: 0,
};

export function snapshotFor(
  status: SessionStatus,
  sessionId: number,
  error?: unknown,
): SessionSnapshot {
  const authenticated = status === "authenticated";
  return {
    status,
    canQueryPersonal: authenticated,
    canAct: authenticated,
    ...(status === "error" ? { error } : {}),
    sessionId,
  };
}

function isApiError(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}

/**
 * Outcome of the boot refresh, as reported by the transport.
 *
 * `anonymous` is the ordinary "no cookie" answer and stays quiet. A transport
 * or 5xx failure is `error`, so the UI can offer a retry instead of claiming
 * the visitor signed out.
 */
export function statusFromRestore(
  result: { status: "authenticated" | "anonymous" | "error" | "superseded"; error?: unknown },
  current: SessionSnapshot,
): SessionSnapshot {
  switch (result.status) {
    case "authenticated":
      return snapshotFor("authenticated", current.sessionId + 1);
    case "anonymous":
      return snapshotFor("anonymous", current.sessionId);
    case "superseded":
      // Another transition owns the state; re-read rather than guess.
      return current;
    default:
      return snapshotFor("error", current.sessionId, result.error);
  }
}

/**
 * Status after a personal read failed.
 *
 * 401/403 are authorization answers (`expired`, or `anonymous` if no session
 * was ever established). Everything else — offline, DNS, 5xx, abort — is
 * `error` and must not be rendered as "you are not allowed".
 */
export function statusFromProbeFailure(
  error: unknown,
  current: SessionSnapshot,
): SessionSnapshot {
  if (isApiError(error, 401) || isApiError(error, 403)) {
    return snapshotFor(current.sessionId > 0 ? "expired" : "anonymous", current.sessionId);
  }
  return snapshotFor("error", current.sessionId, error);
}

/** True when the visitor came from (or is looking at) a page that needs no account. */
export function isPublicPath(pathname: string, base = "/"): boolean {
  const prefix = base.endsWith("/") ? base.slice(0, -1) : base;
  const path = pathname.startsWith(prefix) ? pathname.slice(prefix.length) || "/" : pathname;
  return !path.startsWith("/login") && !path.startsWith("/analyses");
}