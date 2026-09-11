import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("@soymutdb/api-client", () => ({ http: { post } }));

import { StaticPageMigrationReport } from "./static-page-migration-report";

function renderReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StaticPageMigrationReport />
    </QueryClientProvider>,
  );
}

describe("StaticPageMigrationReport", () => {
  it("calls only the dry-run endpoint and renders safe report fields", async () => {
    post.mockResolvedValueOnce({
      dry_run: true,
      created: 1,
      skipped: 0,
      invalid: 1,
      items: [
        {
          static_page_id: 7,
          slug: "legacy-about",
          route: "/pages/legacy-about",
          outcome: "created",
          error_code: null,
          message: null,
        },
        {
          static_page_id: 8,
          slug: "legacy-bad",
          route: "/pages/legacy-bad",
          outcome: "invalid",
          error_code: "invalid_static_page",
          message: "The legacy page cannot be converted to a Page Builder draft.",
        },
      ],
    });
    renderReport();

    fireEvent.click(screen.getByRole("button", { name: "Preview migration" }));

    expect(await screen.findByText("Dry run: 1 ready, 0 already mapped, 1 needs review.")).toBeInTheDocument();
    expect(screen.getByText("legacy-about")).toBeInTheDocument();
    expect(screen.getByText("The legacy page cannot be converted to a Page Builder draft.")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith(
      "/admin/content/pages/migrate-to-page-builder/dry-run",
      { json: {} },
    );
    expect(post.mock.calls[0][0]).toContain("dry-run");
    expect(screen.queryByRole("button", { name: /apply|publish|migrate now/i })).not.toBeInTheDocument();
  });
});
