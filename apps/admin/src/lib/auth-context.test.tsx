import * as React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAuth,
  getAccessToken,
  http,
  onAuthLogout,
  restoreSession,
  setAccessToken,
} from "@soymutdb/api-client";

import { AuthProvider, LoginSupersededError, useAuth } from "./auth-context";
import { createQueryClient } from "./query-client";

/**
 * Session-boundary regressions.
 *
 * AuthProvider outlives every auth request it starts, so each test below
 * drives one identity transition (logout, hard session death, a competing
 * login) against a request that is still in flight, and asserts the late
 * response cannot write the previous identity back into the context or back
 * into the query cache.
 *
 * The only protection before this file existed was an effect-local
 * "cancelled" flag, which fires on unmount and never on an identity change.
 */
vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
      download: vi.fn(),
    },
    getAccessToken: vi.fn(() => null),
    setAccessToken: vi.fn(),
    clearAuth: vi.fn(),
    restoreSession: vi.fn(() => Promise.resolve(false)),
    onAuthLogout: vi.fn(() => () => {}),
  };
});

/** A promise whose settlement the test controls. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** JWT carrying only the human-readable claims the provider may display. */
function accessTokenFor(username: string): string {
  const payload = btoa(JSON.stringify({ username, sub: "6f1c2b74-0000-0000-0000-000000000000" }));
  return "header." + payload + ".signature";
}

/** Surfaces the auth context so assertions read live provider state. */
let latestAuth: ReturnType<typeof useAuth> | null = null;
function AuthProbe() {
  latestAuth = useAuth();
  return (
    <div>
      <span data-testid="authed">{String(latestAuth.isAuthenticated)}</span>
      <span data-testid="user">{latestAuth.user?.username ?? "none"}</span>
    </div>
  );
}

/** Captured the way the real auth layer registers hard session death. */
let logoutHandlers: Array<() => void> = [];

// AuthProvider lives outside the router, so it leaves the console by assigning
// window.location.href. jsdom cannot navigate and reports it as an
// unimplemented error, so the target is captured instead.
let redirects: string[] = [];
const realLocation = window.location;

let queryClient: ReturnType<typeof createQueryClient>;

function renderAuthed(children?: React.ReactNode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthProbe />
        {children}
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  queryClient = createQueryClient();
  latestAuth = null;
  logoutHandlers = [];
  redirects = [];
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: {
      set href(next: string) {
        redirects.push(next);
      },
      get href() {
        return redirects[redirects.length - 1] ?? "/";
      },
    },
  });
  vi.mocked(restoreSession).mockResolvedValue(false);
  vi.mocked(getAccessToken).mockReturnValue(null);
  vi.mocked(onAuthLogout).mockImplementation((handler) => {
    logoutHandlers.push(handler);
    return () => {
      const index = logoutHandlers.indexOf(handler);
      if (index >= 0) logoutHandlers.splice(index, 1);
    };
  });
  vi.mocked(http.get).mockResolvedValue(undefined);
  vi.mocked(http.post).mockResolvedValue({});
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

describe("AuthProvider session boundaries", () => {
  it("does not let a restore landing after logout repaint the old identity", async () => {
    const me = deferred<{ username: string; full_name: string }>();
    vi.mocked(restoreSession).mockResolvedValue(true);
    vi.mocked(getAccessToken).mockReturnValue(accessTokenFor("alice"));
    vi.mocked(http.get).mockReturnValue(me.promise as never);

    renderAuthed();
    await waitFor(() => expect(http.get).toHaveBeenCalledWith("/auth/me", expect.anything()));

    act(() => latestAuth!.logout());
    expect(screen.getByTestId("authed")).toHaveTextContent("false");

    // The boot restore's profile call finally answers, naming the old user.
    await act(async () => {
      me.resolve({ username: "alice", full_name: "Alice" });
      await me.promise;
    });

    expect(screen.getByTestId("authed")).toHaveTextContent("false");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("discards a login that resolves after logout instead of reinstalling its token", async () => {
    const loginPost = deferred<{
      access_token: string;
      token_type: string;
      expires_in: number;
    }>();
    vi.mocked(http.post).mockImplementation((path: string) =>
      path === "/auth/login" ? (loginPost.promise as never) : (Promise.resolve({}) as never),
    );

    renderAuthed();
    await waitFor(() => expect(latestAuth).not.toBeNull());

    const pending = latestAuth!.login("mallory", "secret");
    const settled = pending.then(
      () => "resolved",
      (err: unknown) => err,
    );

    act(() => latestAuth!.logout());
    expect(clearAuth).toHaveBeenCalled();

    await act(async () => {
      loginPost.resolve({
        access_token: accessTokenFor("mallory"),
        token_type: "bearer",
        expires_in: 900,
      });
      await settled;
    });

    // The token arrived after clearAuth(); installing it would hand the console
    // a credential for the session the operator just closed.
    expect(setAccessToken).not.toHaveBeenCalled();
    expect(await settled).toBeInstanceOf(LoginSupersededError);
    expect(screen.getByTestId("authed")).toHaveTextContent("false");
  });

  it("does not let a slow restore overwrite a freshly logged-in user", async () => {
    const restoreMe = deferred<{ username: string }>();
    let meCalls = 0;
    vi.mocked(restoreSession).mockResolvedValue(true);
    vi.mocked(getAccessToken).mockReturnValue(accessTokenFor("alice"));
    vi.mocked(http.get).mockImplementation((path: string) => {
      if (path !== "/auth/me") return Promise.resolve(undefined) as never;
      meCalls += 1;
      const next =
        meCalls === 1
          ? restoreMe.promise
          : Promise.resolve({ username: "bob", full_name: "Bob" });
      return next as never;
    });
    vi.mocked(http.post).mockImplementation((path: string) =>
      path === "/auth/login"
        ? (Promise.resolve({
            access_token: accessTokenFor("bob"),
            token_type: "bearer",
            expires_in: 900,
          }) as never)
        : (Promise.resolve({}) as never),
    );

    renderAuthed();
    await waitFor(() => expect(http.get).toHaveBeenCalledWith("/auth/me", expect.anything()));

    // A different operator completes a login while the boot restore is pending.
    await act(async () => {
      await latestAuth!.login("bob", "hunter2");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("bob");

    // The boot restore's stale profile finally arrives, naming the old user.
    await act(async () => {
      restoreMe.resolve({ username: "alice" });
      await restoreMe.promise;
    });

    expect(screen.getByTestId("user")).toHaveTextContent("bob");
    expect(screen.getByTestId("authed")).toHaveTextContent("true");
  });

  it("clears the previous identity's cache when a hard session death fires", async () => {
    vi.mocked(restoreSession).mockResolvedValue(true);
    vi.mocked(getAccessToken).mockReturnValue(accessTokenFor("alice"));
    vi.mocked(http.get).mockResolvedValue({ username: "alice" } as never);

    renderAuthed();
    await waitFor(() => expect(screen.getByTestId("authed")).toHaveTextContent("true"));

    queryClient.setQueryData(["admin", "audit"], [{ id: 1, actor: "alice" }]);

    await act(async () => {
      logoutHandlers.forEach((handler) => handler());
    });

    expect(screen.getByTestId("authed")).toHaveTextContent("false");
    expect(queryClient.getQueryData(["admin", "audit"])).toBeUndefined();
  });

  it("clears the previous identity's cache on logout", async () => {
    vi.mocked(restoreSession).mockResolvedValue(true);
    vi.mocked(getAccessToken).mockReturnValue(accessTokenFor("alice"));
    vi.mocked(http.get).mockResolvedValue({ username: "alice" } as never);

    renderAuthed();
    await waitFor(() => expect(screen.getByTestId("authed")).toHaveTextContent("true"));

    queryClient.setQueryData(["admin", "settings"], { theme: "dark" });

    await act(async () => {
      latestAuth!.logout();
    });

    expect(queryClient.getQueryData(["admin", "settings"])).toBeUndefined();
    // Leaving the console by full navigation is unchanged behaviour.
    expect(redirects).toEqual(["/login"]);
  });

  it("clears the previous identity's cache when another operator logs in", async () => {
    renderAuthed();
    await waitFor(() => expect(latestAuth).not.toBeNull());

    queryClient.setQueryData(["admin", "audit"], [{ id: 1, actor: "alice" }]);
    vi.mocked(http.post).mockImplementation((path: string) =>
      path === "/auth/login"
        ? (Promise.resolve({
            access_token: accessTokenFor("bob"),
            token_type: "bearer",
            expires_in: 900,
          }) as never)
        : (Promise.resolve({}) as never),
    );
    vi.mocked(http.get).mockResolvedValue({ username: "bob" } as never);

    await act(async () => {
      await latestAuth!.login("bob", "hunter2");
    });

    expect(screen.getByTestId("user")).toHaveTextContent("bob");
    expect(queryClient.getQueryData(["admin", "audit"])).toBeUndefined();
  });

  it("keeps an in-flight query from painting the previous identity's rows after logout", async () => {
    const rows = deferred<string[]>();

    function AuditList() {
      const query = useQuery({
        queryKey: ["admin", "audit"],
        queryFn: () => rows.promise,
        retry: false,
      });
      return <span data-testid="rows">{(query.data ?? []).join(",") || "empty"}</span>;
    }

    vi.mocked(restoreSession).mockResolvedValue(true);
    vi.mocked(getAccessToken).mockReturnValue(accessTokenFor("alice"));
    vi.mocked(http.get).mockResolvedValue({ username: "alice" } as never);

    renderAuthed(<AuditList />);
    await waitFor(() => expect(screen.getByTestId("authed")).toHaveTextContent("true"));

    await act(async () => {
      latestAuth!.logout();
      await Promise.resolve();
    });

    // The request issued as alice lands after the boundary. Cancelling the
    // query is what stops its observer from rendering the stale payload.
    await act(async () => {
      rows.resolve(["alice-only-row"]);
      await rows.promise;
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByTestId("rows")).toHaveTextContent("empty");
  });
});
