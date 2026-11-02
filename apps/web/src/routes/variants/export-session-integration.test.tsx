// @vitest-environment jsdom
/** Real session/query owners and page; transport, router and presentation wrappers are mocked. */
import * as React from "react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({
  submit: vi.fn(),
  status: vi.fn(),
  download: vi.fn(),
  logoutListeners: new Set<() => void>(),
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({
    options,
    useSearch: () => ({ assembly: "1", chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "" }),
  }),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../../lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../lib/use-current-user", () => ({
  // The capability wrapper is mocked like the transport: the session and the
  // query owners stay real, the server's role answer does not.
  useIsResearcher: () => ({ isResearcher: true, isLoading: false }),
}));
vi.mock("../../lib/release-scope", () => ({
  // The pinned release is a React value, not a module read: the route
  // has to re-render when an operator publishes a new release.
  useReleaseId: () => "1",
}));
vi.mock("@soymutdb/api-client", async (importOriginal) => ({
  ...await importOriginal<typeof import("@soymutdb/api-client")>(),
  getReleaseId: () => "1",
  getAssemblies: async () => [{ id: 1, name: "Wm82.a4.v1", is_default: true }],
  searchVariants: async () => ({ items: [], has_more: false, next_cursor: null }),
  createVariantExport: (...args: unknown[]) => transport.submit(...args),
  getVariantExportStatus: (...args: unknown[]) => transport.status(...args),
  getVariantExportDownload: (...args: unknown[]) => transport.download(...args),
  restoreSessionResult: async () => ({ status: "authenticated", generation: 1 }),
  refreshAccessTokenResult: async () => ({ status: "authenticated", generation: 2 }),
  onAuthLogout: (listener: () => void) => {
    transport.logoutListeners.add(listener);
    return () => { transport.logoutListeners.delete(listener); };
  },
  clearAuth: () => {},
  setAccessToken: () => {},
}));

import { SessionProvider, useSession } from "../../lib/session-context";
import { queryKeys } from "../../lib/query-keys";
import { Route } from "./index";

const Page = (Route.options as { component: React.ComponentType }).component;
const clients: QueryClient[] = [];

function SessionControls() {
  const session = useSession();
  return <>
    <output data-testid="session-scope">{session.sessionId}:{session.status}</output>
    <button onClick={session.signOut}>Sign out</button>
    <button onClick={() => void session.adoptSignIn("account-b-token")}>Sign in B</button>
  </>;
}

async function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}>
    <SessionProvider queryClient={client}><SessionControls /><Page /></SessionProvider>
  </QueryClientProvider>);
  await waitFor(() => expect(screen.getByTestId("session-scope").textContent).toBe("1:authenticated"));
  await waitFor(() => expect(screen.getByRole("button", { name: /variants.export$/ }).hasAttribute("disabled")).toBe(false));
  return client;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}

beforeEach(() => {
  transport.submit.mockReset().mockResolvedValue({ export_id: "account-a-export", message: "A submitted" });
  transport.status.mockReset().mockResolvedValue({ status: "succeeded" });
  transport.download.mockReset();
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  focusManager.setFocused(undefined);
  vi.restoreAllMocks();
});

describe("variant export with the real session and query owners", () => {
  it.each(["signout", "expiry"])("removes old cached UI/observers on %s with unchanged sessionId", async (boundary) => {
    const client = await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await screen.findByTestId("variant-export-download");
    const key = queryKeys.variants.export("account-a-export", 1);
    expect(client.getQueryData(key)).toEqual({ status: "succeeded" });
    const reads = transport.status.mock.calls.length;

    if (boundary === "signout") {
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    } else {
      act(() => { for (const notify of transport.logoutListeners) notify(); });
    }
    expect(screen.getByTestId("session-scope").textContent).toBe(
      boundary === "signout" ? "1:anonymous" : "1:expired",
    );
    expect(screen.queryByTestId("variant-export-download")).toBeNull();
    expect(screen.queryByTestId("variant-export-progress")).toBeNull();
    expect(screen.queryByTestId("variant-export-status")).toBeNull();
    expect(client.getQueryCache().find({ queryKey: key })?.getObserversCount()).toBe(0);

    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      await client.invalidateQueries({ refetchType: "active" });
    });
    expect(transport.status).toHaveBeenCalledTimes(reads);
    // Cache retention is not deletion: stale data is inactive and not rendered.
    expect(client.getQueryData(key)).toEqual({ status: "succeeded" });
  });

  it("keeps an in-flight status response inactive after logout", async () => {
    const pending = deferred<{ status: string; error_message: string }>();
    transport.status.mockReturnValue(pending.promise);
    const client = await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await waitFor(() => expect(transport.status).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await act(async () => { pending.resolve({ status: "failed", error_message: "A private status" }); });
    expect(screen.queryByTestId("variant-export-error")).toBeNull();
    expect(screen.queryByText("A private status")).toBeNull();
    expect(screen.queryByTestId("variant-export-progress")).toBeNull();
    const key = queryKeys.variants.export("account-a-export", 1);
    expect(client.getQueryData(key)).toEqual({ status: "failed", error_message: "A private status" });
    expect(client.getQueryCache().find({ queryKey: key })?.getObserversCount()).toBe(0);
    expect(client.getQueryData(queryKeys.variants.export("account-a-export", 2))).toBeUndefined();
    await act(async () => { await client.invalidateQueries({ refetchType: "active" }); });
    expect(transport.status).toHaveBeenCalledTimes(1);
  });

  it("does not adopt A's late submission after actual logout and B sign-in", async () => {
    const pending = deferred<{ export_id: string; message: string }>();
    transport.submit.mockReturnValue(pending.promise);
    const client = await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    expect(transport.submit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign in B" }));
    await waitFor(() => expect(screen.getByTestId("session-scope").textContent).toBe("2:authenticated"));
    await act(async () => { pending.resolve({ export_id: "account-a-export", message: "A submitted" }); });
    expect(screen.queryByTestId("variant-export-status")).toBeNull();
    expect(screen.queryByTestId("variant-export-progress")).toBeNull();
    expect(transport.status).not.toHaveBeenCalled();
    expect(client.getQueryData(queryKeys.variants.export("account-a-export", 2))).toBeUndefined();
  });

  it("hides the old download error and never opens A's late signed link", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    const download = await screen.findByTestId("variant-export-download");
    transport.download.mockRejectedValueOnce(new Error("A download unavailable"));
    fireEvent.click(download);
    expect((await screen.findByTestId("variant-export-download-error")).textContent).toBe("A download unavailable");
    const pending = deferred<{ download_url: string }>();
    transport.download.mockReturnValueOnce(pending.promise);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(download);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.queryByTestId("variant-export-download-error")).toBeNull();
    expect(screen.queryByTestId("variant-export-download")).toBeNull();
    await act(async () => { pending.resolve({ download_url: "https://minio.test/account-a" }); });
    expect(click).not.toHaveBeenCalled();
  });
});
