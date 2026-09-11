import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth-context";

const { restoreSessionMock, getAccessTokenMock, onAuthLogoutMock } = vi.hoisted(() => ({
  restoreSessionMock: vi.fn(),
  getAccessTokenMock: vi.fn(),
  onAuthLogoutMock: vi.fn(() => vi.fn()),
}));

vi.mock("@soymutdb/api-client", () => ({
  http: { post: vi.fn() },
  getAccessToken: getAccessTokenMock,
  setAccessToken: vi.fn(),
  clearAuth: vi.fn(),
  restoreSession: restoreSessionMock,
  onAuthLogout: onAuthLogoutMock,
}));

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("AuthProvider session restoration", () => {
  beforeEach(() => {
    restoreSessionMock.mockReset();
    getAccessTokenMock.mockReset();
    onAuthLogoutMock.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the auth boundary in restoring state until a successful session restore settles", async () => {
    let resolveRestore!: (value: boolean) => void;
    restoreSessionMock.mockReturnValue(new Promise<boolean>((resolve) => { resolveRestore = resolve; }));
    getAccessTokenMock.mockReturnValue("header.eyJzdWIiOiJhZG1pbiJ9.signature");

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isRestoringSession).toBe(true);
    expect(result.current.isAuthenticated).toBe(false);

    await act(async () => { resolveRestore(true); });

    await waitFor(() => expect(result.current.isRestoringSession).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user).toEqual({ username: "admin" });
  });

  it("settles anonymous only after a failed session restore", async () => {
    restoreSessionMock.mockResolvedValue(false);

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isRestoringSession).toBe(true);
    await waitFor(() => expect(result.current.isRestoringSession).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
  });
});
