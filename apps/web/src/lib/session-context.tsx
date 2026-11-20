/**
 * React binding for the portal session state machine.
 *
 * One coordinator, one owner: `packages/api-client/src/auth.ts` keeps the
 * token, the refresh single-flight and the logout event; this provider turns
 * that into a reactive value the component tree can read. There is no second
 * token store and no second refresh path.
 *
 * Boot uses `restoreSessionResult()` — the same single-flight the 401 handler
 * uses — so a public page that mounts during boot joins the attempt already in
 * progress instead of starting another one.
 */
import * as React from "react";
import { QueryClient } from "@tanstack/react-query";
import {
  clearAuth,
  clearSessionHint,
  onAuthLogout,
  restoreSessionResult,
  refreshAccessTokenResult,
  setAccessToken,
} from "@soymutdb/api-client";

import {
  INITIAL_SESSION,
  isPublicPath,
  snapshotFor,
  statusFromRestore,
  type SessionSnapshot,
  type SessionStatus,
} from "./session";

export interface SessionContextValue extends SessionSnapshot {
  /** Re-run the boot refresh after a transport failure. */
  retry: () => void;
  /** Adopt a token issued by the sign-in form. */
  adoptSignIn: (accessToken: string) => Promise<void>;
  /** Drop the in-memory session and every personal cache entry. */
  signOut: () => void;
}

const SessionContext = React.createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const value = React.useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside <SessionProvider>");
  }
  return value;
}

export interface SessionProviderProps {
  children: React.ReactNode;
  queryClient: QueryClient;
  /** Injected in tests; defaults to the real transport. */
  restore?: typeof restoreSessionResult;
}

/** Personal queries are keyed by `sessionId`, so a new account starts empty. */
const PERSONAL_QUERY_KEY = ["current-user"] as const;

export function SessionProvider({
  children,
  queryClient,
  restore = restoreSessionResult,
}: SessionProviderProps): React.ReactElement {
  const [session, setSession] = React.useState<SessionSnapshot>(INITIAL_SESSION);
  const mounted = React.useRef(true);

  const run = React.useCallback(() => {
    setSession((current) => snapshotFor("restoring", current.sessionId, current.error));
    void restore().then((result) => {
      if (!mounted.current) return;
      setSession((current) => statusFromRestore(result, current));
    });
  }, [restore]);

  React.useEffect(() => {
    mounted.current = true;
    run();
    return () => {
      mounted.current = false;
    };
  }, [run]);

  // The transport owns the decision that a session died. This provider owns
  // what the portal does about it: a public page keeps rendering (H-07), a
  // page that needs an account offers a sign-in with a validated return path.
  React.useEffect(
    () =>
      onAuthLogout(() => {
        if (!mounted.current) return;
        setSession((current) =>
          current.status === "authenticated"
            ? snapshotFor("expired", current.sessionId)
            : current,
        );
        queryClient.removeQueries({ queryKey: PERSONAL_QUERY_KEY });
        if (typeof window === "undefined") return;
        const base = import.meta.env.BASE_URL ?? "/";
        if (isPublicPath(window.location.pathname, base)) return;
        const loginPath = `${base.endsWith("/") ? base.slice(0, -1) : base}/login`;
        const next = `${loginPath}?redirect=${encodeURIComponent(
          window.location.pathname + window.location.search,
        )}`;
        window.location.href = next;
      }),
    [queryClient],
  );

  const adoptSignIn = React.useCallback(
    async (accessToken: string) => {
      setAccessToken(accessToken);
      // A previous account's personal data must not survive the switch.
      queryClient.removeQueries({ queryKey: PERSONAL_QUERY_KEY });
      const result = await refreshAccessTokenResult();
      if (!mounted.current) return;
      setSession((current) =>
        result.status === "authenticated"
          ? statusFromRestore(result, current)
          : snapshotFor("authenticated", current.sessionId + 1),
      );
    },
    [queryClient],
  );

  const signOut = React.useCallback(() => {
    clearAuth();
    // An explicit sign-out ends this browser's session: the next boot must not
    // ask the server for a session that no longer exists.
    clearSessionHint();
    queryClient.removeQueries({ queryKey: PERSONAL_QUERY_KEY });
    setSession((current) => snapshotFor("anonymous", current.sessionId));
  }, [queryClient]);

  const retry = React.useCallback(() => run(), [run]);

  const value = React.useMemo<SessionContextValue>(
    () => ({ ...session, retry, adoptSignIn, signOut }),
    [session, retry, adoptSignIn, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export type { SessionSnapshot, SessionStatus };