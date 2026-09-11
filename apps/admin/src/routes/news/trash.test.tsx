import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { App as AntdApp } from "../../lib/antd";
import NewsTrashPage from "./trash";
import { listDeletedAdminNews, purgeNews, restoreNews } from "@soymutdb/api-client";

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: ... })` returns a new function per render and makes any
// component with `t` in an effect dependency loop forever. See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@tanstack/react-router", () => ({ useRouter: () => ({ navigate: vi.fn() }) }));
vi.mock("@soymutdb/api-client", () => ({ listDeletedAdminNews: vi.fn(), purgeNews: vi.fn(), restoreNews: vi.fn() }));

const listMock = vi.mocked(listDeletedAdminNews);
const purgeMock = vi.mocked(purgeNews);
const restoreMock = vi.mocked(restoreNews);
const article = { id: 9, title_en: "Deleted article", title_zh: null, slug: "deleted-article", category: "news", status: "published" as const, published_at: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", deleted_at: "2026-01-02T00:00:00Z" };

function renderPage() { return render(<AntdApp><NewsTrashPage /></AntdApp>); }

beforeEach(() => {
  listMock.mockReset(); purgeMock.mockReset(); restoreMock.mockReset();
  listMock.mockResolvedValue({ items: [article], total: 1, page: 1, page_size: 10 });
});

describe("NewsTrashPage", () => {
  it("requests only pagination and renders no body or preview controls", async () => {
    renderPage();
    await screen.findByText("Deleted article");
    expect(listMock).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    expect(screen.queryByText(/content_html|preview|edit/i)).not.toBeInTheDocument();
  });

  it("requires exact slug before permanently deleting", async () => {
    const user = userEvent.setup(); renderPage(); await screen.findByText("Deleted article");
    await user.click(screen.getByRole("button", { name: "admin.news.trash.purge" }));
    const confirm = screen.getAllByRole("button", { name: "admin.news.trash.purge" }).at(-1)!;
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("admin.news.trash.slug"), "wrong");
    expect(confirm).toBeDisabled();
    await user.clear(screen.getByLabelText("admin.news.trash.slug"));
    await user.type(screen.getByLabelText("admin.news.trash.slug"), article.slug);
    expect(confirm).toBeEnabled();
  });

  it("purges only after exact slug, then reloads", async () => {
    const user = userEvent.setup(); purgeMock.mockResolvedValue(); renderPage();
    await screen.findByText("Deleted article");
    await user.click(screen.getByRole("button", { name: "admin.news.trash.purge" }));
    await user.type(screen.getByLabelText("admin.news.trash.slug"), article.slug);
    await user.click(screen.getAllByRole("button", { name: "admin.news.trash.purge" }).at(-1)!);
    await waitFor(() => expect(purgeMock).toHaveBeenCalledWith(9));
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
  });

  it("keeps purge confirmation open after a failed request", async () => {
    const user = userEvent.setup(); purgeMock.mockRejectedValue(new Error("offline")); renderPage();
    await screen.findByText("Deleted article");
    await user.click(screen.getByRole("button", { name: "admin.news.trash.purge" }));
    await user.type(screen.getByLabelText("admin.news.trash.slug"), article.slug);
    await user.click(screen.getAllByRole("button", { name: "admin.news.trash.purge" }).at(-1)!);
    await waitFor(() => expect(purgeMock).toHaveBeenCalledWith(9));
    expect(screen.getByLabelText("admin.news.trash.slug")).toBeInTheDocument();
  });

  it("reloads after restore success", async () => {
    const user = userEvent.setup(); restoreMock.mockResolvedValue({} as never);
    renderPage(); await screen.findByText("Deleted article");
    await user.click(screen.getByRole("button", { name: "admin.news.trash.restore" }));
    await user.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(restoreMock).toHaveBeenCalledWith(9));
  });
});
