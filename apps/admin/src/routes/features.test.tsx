/**
 * Feature-flag console contract.
 *
 * Two defects are pinned here:
 *
 * 1. A rejected toggle used to be swallowed — the mutation had no `onError`,
 *    so the switch kept its old value and the operator was told nothing.
 * 2. A successful toggle only invalidated `["admin-features"]`, while the
 *    same screen and the import page read `["public-capabilities"]` with a
 *    30 s stale window. Disabling `imports.module_tsv` therefore left the
 *    import page offering module imports for up to half a minute.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  adminGet: vi.fn(),
  get: vi.fn(),
  adminUpdate: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    capabilitiesApi: {
      adminGet: api.adminGet,
      get: api.get,
      adminUpdate: api.adminUpdate,
    },
  };
});

const FeaturesPage = (await import("./features")).default;

const FEATURE = {
  key: "imports.module_tsv",
  enabled: true,
  default: true,
  public: true,
  description: "Module imports",
  disable_behavior: "reject_new",
};

const PUBLIC_CAPABILITIES = {
  version: 1,
  features: { "imports.module_tsv": true },
  plugins: {},
  databases: { authoritative: "postgresql", analytics: null },
};

beforeEach(() => {
  api.adminGet.mockReset().mockResolvedValue({ version: 1, features: [FEATURE] });
  api.get.mockReset().mockResolvedValue(PUBLIC_CAPABILITIES);
  api.adminUpdate.mockReset().mockResolvedValue({ version: 2, features: [FEATURE] });
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={queryClient}>
      <FeaturesPage />
    </QueryClientProvider>,
  );
  return { queryClient, invalidate, ...view };
}

describe("feature flag console", () => {
  it("does not label an unknown plugin runtime as ready while pending or failed", async () => {
    let rejectRequest!: (error: Error) => void;
    api.get.mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    renderPage();
    expect(screen.getByText("Loading plugin status…")).toBeInTheDocument();
    expect(screen.queryByText("ready")).toBeNull();
    rejectRequest(new Error("capabilities unavailable"));
    expect(await screen.findByRole("alert", { name: "Plugin status unavailable" })).toBeInTheDocument();
    expect(screen.queryByText("ready")).toBeNull();
    expect(screen.queryByText("Available")).toBeNull();
  });
  it("reports a rejected toggle instead of leaving the old value in place", async () => {
    api.adminUpdate.mockRejectedValueOnce(new Error("capability is locked"));
    renderPage();

    const toggle = await screen.findByRole("button", { name: /Disable imports\.module_tsv/ });
    fireEvent.click(toggle);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("imports.module_tsv");
    expect(alert).toHaveTextContent("capability is locked");
  });

  it("invalidates the public-capabilities cache key after a toggle", async () => {
    const { invalidate, queryClient } = renderPage();

    // Seed the public snapshot the import page reads, so the invalidation has
    // a live cache entry to act on.
    queryClient.setQueryData(["public-capabilities"], PUBLIC_CAPABILITIES);

    const toggle = await screen.findByRole("button", { name: /Disable imports\.module_tsv/ });
    fireEvent.click(toggle);

    await waitFor(() => expect(api.adminUpdate).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin-features"] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["public-capabilities"] });
    });

    // The stale public snapshot must be refetched, not merely marked stale.
    await waitFor(() => expect(api.get.mock.calls.length).toBeGreaterThan(1));
  });
});
