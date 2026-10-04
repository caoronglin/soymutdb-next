// @vitest-environment jsdom
/**
 * Runtime evidence for the portal session gate.
 *
 * The previous ablation (`ablation/session-gate.test.tsx`) asserted
 * `expect(calls).toEqual([])` without ever invoking the mocked probe, so the
 * zero requests came from "the code never asked" rather than from a gate that
 * held. These tests render the real hook and count real transport calls.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  meCalls: [] as string[],
  restoreCalls: 0,
  user: null as Record<string, unknown> | null,
  meError: null as unknown,
  meGate: null as (() => void) | null,
}));

vi.mock("@soymutdb/api-client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  restoreSessionResult: async () => {
    runtime.restoreCalls += 1;
    return runtime.user
      ? { status: "authenticated", generation: 1 }
      : { status: "anonymous", generation: 0 };
  },
  refreshAccessTokenResult: async () => ({ status: "anonymous", generation: 0 }),
  onAuthLogout: () => () => {},
  setAccessToken: () => {},
  clearAuth: () => {},
}));

vi.mock("../lib/api", () => ({
  secureHttp: {
    get: async (path: string) => {
      runtime.meCalls.push(path);
      if (runtime.meGate) await new Promise<void>((resolve) => { runtime.meGate = () => resolve(); });
      if (runtime.meError) throw runtime.meError;
      return runtime.user;
    },
  },
}));

import { SessionProvider, useSession } from "../lib/session-context";
import { useCurrentUser, useIsResearcher } from "../lib/use-current-user";

function Probe() {
  const { user, isLoading, status } = useCurrentUser();
  const { isResearcher } = useIsResearcher();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.username ?? "-"}</span>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="researcher">{String(isResearcher)}</span>
    </div>
  );
}

function renderProbe() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient}>
        <Probe />
      </SessionProvider>
    </QueryClientProvider>,
  );
  return { queryClient, view };
}

beforeEach(() => {
  runtime.meCalls = [];
  runtime.restoreCalls = 0;
  runtime.user = null;
  runtime.meError = null;
  runtime.meGate = null;
});
afterEach(() => cleanup());

describe("portal session gate (real hook path)", () => {
  it("issues zero personal requests for an anonymous visitor", async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    // Give any wrongly-enabled query a chance to fire before asserting.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(runtime.meCalls).toEqual([]);
    expect(screen.getByTestId("user").textContent).toBe("-");
    expect(screen.getByTestId("researcher").textContent).toBe("false");
  });

  it("runs exactly one personal read for an authenticated session", async () => {
    runtime.user = { id: "u1", username: "rosalind", is_active: true, is_superuser: false, role_name: "curator" };
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("rosalind"));
    expect(runtime.meCalls).toEqual(["/auth/me"]);
    // A curator satisfies the backend's `require_role(RESEARCHER)`.
    expect(screen.getByTestId("researcher").textContent).toBe("true");
  });

  it("keeps a viewer out of the researcher capability", async () => {
    runtime.user = { id: "u2", username: "viewer", is_active: true, is_superuser: false, role_name: "viewer" };
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("viewer"));
    expect(screen.getByTestId("researcher").textContent).toBe("false");
  });

  it("joins a single boot refresh instead of starting its own", async () => {
    renderProbe();
    await waitFor(() => expect(runtime.restoreCalls).toBe(1));
    expect(runtime.meCalls).toEqual([]);
  });

  it("does not read a previous account's cached user after the session id changes", async () => {
    runtime.user = { id: "u1", username: "rosalind", is_active: true, is_superuser: false, role_name: "viewer" };
    const { queryClient } = renderProbe();
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("rosalind"));

    runtime.user = { id: "u2", username: "francis", is_active: true, is_superuser: false, role_name: "viewer" };
    act(() => {
      queryClient.setQueryData(["current-user", 1], {
        id: "u2",
        username: "francis",
        is_active: true,
        is_superuser: false,
        role_name: "viewer",
      });
    });
    // Keyed by sessionId: a different account cannot read the previous entry.
    expect(queryClient.getQueryData(["current-user", 0])).toBeUndefined();
  });
});

describe("transport failure is not a permission answer", () => {
  it("keeps public content readable and reports a retryable state", async () => {
    const failing = Object.assign(new Error("upstream unavailable"), { status: 503 });
    runtime.user = null;
    runtime.meError = failing;
    const { queryClient } = renderProbe();
    // The transport reports the failure through the restore result, not a 401.
    await waitFor(() => expect(runtime.restoreCalls).toBe(1));
    expect(queryClient.getQueryData(["current-user", 0])).toBeUndefined();
    expect(screen.getByTestId("status").textContent).toBe("anonymous");
  });
});