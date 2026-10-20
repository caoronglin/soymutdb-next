/**
 * Static-page console contract.
 *
 * Publish, unpublish and delete are externally visible or destructive
 * actions. Publish/unpublish fired on a single click with no confirmation,
 * none of the three mutations had an `onError`, and the shared confirm dialog
 * had no way to explain a rejected write.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../../test/antd-double")));

const router = vi.hoisted(() => ({ navigate: vi.fn() }));

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => router.navigate,
  useSearch: () => ({}),
  Link: (props: { children?: React.ReactNode }) => <a>{props.children}</a>,
}));

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: api.get,
      post: api.post,
      delete: api.delete,
    },
  };
});

const { PagesTab } = await import("./pages-tab");

const PAGE = {
  id: "page-1",
  slug: "about",
  title_en: "About SoyMutDB",
  title_zh: null,
  content_en: "",
  content_zh: null,
  summary: null,
  category: "about",
  status: "draft",
  sort_order: 0,
  author_name: null,
  published_at: null,
  current_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const NoopDialog = () => null;

function renderTab(status: "draft" | "published" = "draft") {
  currentStatus = status;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PagesTab
        PageFormDialog={NoopDialog as never}
        VersionHistoryDialog={NoopDialog as never}
        VersionDetail={NoopDialog as never}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  router.navigate.mockReset();
  api.get.mockReset().mockImplementation((url: string) => {
    if (url === "/admin/content/pages") {
      return Promise.resolve({ items: [{ ...PAGE, status: currentStatus }], total: 1 });
    }
    return Promise.reject(new Error("unstubbed GET " + url));
  });
  api.post.mockReset().mockRejectedValue(new Error("publish rejected"));
  api.delete.mockReset().mockRejectedValue(new Error("delete rejected"));
});

let currentStatus: "draft" | "published" = "draft";

describe("static page publish / unpublish / delete", () => {
  it("does not claim an empty list while pending, and reports a failed list", async () => {
    let rejectRequest!: (error: Error) => void;
    api.get.mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    renderTab();
    expect(screen.getByTestId("pages-table")).toHaveAttribute("data-state", "loading");
    expect(screen.queryByText(/No pages found/)).toBeNull();
    rejectRequest(new Error("pages unavailable"));
    expect(await screen.findByTestId("content-pages-load-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByText(/No pages found/)).toBeNull();
  });

  it("keeps a pending publish open and closes only after acceptance", async () => {
    let resolveRequest!: () => void;
    api.post.mockImplementation(() => new Promise<void>((resolve) => { resolveRequest = resolve; }));
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Publish page" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    resolveRequest();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
  it("asks for confirmation before publishing and reports a rejected publish", async () => {
    currentStatus = "draft";
    renderTab("draft");

    const publish = await screen.findByRole("button", { name: "Publish page" });
    fireEvent.click(publish);

    // Nothing is sent until the operator confirms in the dialog.
    expect(api.post).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/admin/content/pages/page-1/publish"),
    );

    const error = await screen.findByTestId("content-publish-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("could not be published");
    expect(error).toHaveTextContent("publish rejected");
  });

  it("asks for confirmation before unpublishing and reports a rejected unpublish", async () => {
    currentStatus = "published";
    renderTab("published");

    const unpublish = await screen.findByRole("button", { name: "Unpublish page" });
    fireEvent.click(unpublish);

    expect(api.post).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Unpublish" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/admin/content/pages/page-1/unpublish"),
    );

    const error = await screen.findByTestId("content-publish-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("could not be unpublished");
    expect(error).toHaveTextContent("publish rejected");
  });

  it("reports a rejected delete inside the confirmation dialog", async () => {
    currentStatus = "draft";
    renderTab("draft");

    const remove = await screen.findByRole("button", { name: "Delete page" });
    fireEvent.click(remove);

    expect(api.delete).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith("/admin/content/pages/page-1"),
    );

    const error = await screen.findByTestId("content-delete-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("could not be deleted");
    expect(error).toHaveTextContent("delete rejected");
  });
});
