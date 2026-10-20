import * as React from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportDraftListItemResponse, ImportDraftResponse } from "@soymutdb/api-client";
import { createQueryClient } from "../../lib/query-client";

import ImportsPage from "../imports";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

// Each surface the page calls is doubled explicitly: the shared client closes
// over its own transport, so replacing only `http` would leave Import Studio on
// the real network. Everything else (page, queries, editor) stays real.
const doubles = vi.hoisted(() => ({
  httpGet: vi.fn(),
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
  updateMapping: vi.fn(),
  capabilities: {
    features: {
      "imports.module_tsv": true,
      "imports.module_xlsx": true,
      "imports.local_upload": true,
    },
  },
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: doubles.httpGet,
      post: vi.fn(),
      delete: vi.fn(),
    },
    capabilitiesApi: {
      ...actual.capabilitiesApi,
      get: vi.fn(() => Promise.resolve(doubles.capabilities)),
    },
    adminImportStudioApi: {
      ...actual.adminImportStudioApi,
      listDrafts: doubles.listDrafts,
      getDraft: doubles.getDraft,
      updateMapping: doubles.updateMapping,
    },
  };
});

// The admin app compiles TSX with the classic React.createElement factory
// (tsconfig sets jsx: "preserve"), so bind the identifier before first render.
(globalThis as unknown as { React: unknown }).React = React;

function draft(overrides: Partial<ImportDraftResponse> = {}): ImportDraftResponse {
  return {
    id: "draft-1",
    dataset_version_id: "version-1",
    module_key: null,
    filename: "genes.tsv",
    object_key: "s3://bucket/genes.tsv",
    checksum_sha256: "a".repeat(64),
    source: "NCBI RefSeq",
    license: "CC0",
    mime_type: "text/tab-separated-values",
    row_count: 10,
    column_count: 5,
    field_mapping: [
      { source_field: "gene_id", target_field: "id", position: 0, transform: {} },
    ],
    validation: {},
    status: "draft",
    committed_at: null,
    created_at: null,
    updated_at: "2026-08-30T00:00:00Z",
    ...overrides,
  };
}

function draftSummary(
  overrides: Partial<ImportDraftListItemResponse> = {},
): ImportDraftListItemResponse {
  return {
    id: "draft-1",
    dataset_version_id: "version-1",
    module_key: null,
    filename: "genes.tsv",
    row_count: 10,
    column_count: 5,
    status: "draft",
    updated_at: "2026-08-30T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <ImportsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  doubles.listDrafts.mockReset().mockResolvedValue([]);
  doubles.getDraft.mockReset().mockRejectedValue(new Error("no draft in this test"));
  doubles.updateMapping.mockReset().mockResolvedValue(draft());
  doubles.httpGet.mockReset().mockImplementation((url: string) => {
    if (url === "/admin/imports") {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 });
    }
    return Promise.reject(new Error("unstubbed GET " + url));
  });
  window.history.replaceState({}, "", "/imports");
});

afterEach(() => {
  vi.unstubAllEnvs();
  window.history.replaceState({}, "", "/");
});

describe("imports page resume flow", () => {
  it("loads the draft named in the resume query and refreshes it after a save", async () => {
    doubles.getDraft.mockResolvedValue(draft());
    doubles.listDrafts.mockResolvedValue([
      draftSummary(),
      draftSummary({ id: "draft-2", filename: "variants.tsv" }),
    ]);
    window.history.replaceState({}, "", "/imports?draft=draft-1");

    renderPage();

    expect(await screen.findByLabelText("Field mapping JSON")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "admin.importPage.resumeDraft" }),
    ).toBeInTheDocument();
    // The resume identity comes from the URL and is the id handed to the API.
    expect(doubles.getDraft).toHaveBeenCalledWith("draft-1");

    // Draft discovery never loses the identity it links to.
    const resumeLinks = screen.getAllByRole("link", {
      name: "admin.importPage.resume",
    });
    expect(resumeLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/imports?draft=draft-1",
      "/imports?draft=draft-2",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() =>
      expect(doubles.updateMapping).toHaveBeenCalledWith("draft-1", [
        { source_field: "gene_id", target_field: "id", position: 0, transform: {} },
      ]),
    );
    // A successful operation refetches the draft and the discovery list.
    await waitFor(() => expect(doubles.getDraft).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(doubles.listDrafts).toHaveBeenCalledTimes(2));
  });

  it("does not request a draft when the page has no resume identity", async () => {
    renderPage();

    await waitFor(() => expect(doubles.listDrafts).toHaveBeenCalledTimes(1));
    expect(doubles.getDraft).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("heading", { name: "admin.importPage.resumeDraft" }),
    ).toBeNull();
  });

  it("keeps the configured admin base path in draft resume links", async () => {
    vi.stubEnv("BASE_URL", "/admin/");
    doubles.listDrafts.mockResolvedValue([draftSummary()]);

    renderPage();

    const link = await screen.findByRole("link", {
      name: "admin.importPage.resume",
    });
    expect(link).toHaveAttribute("href", "/admin/imports?draft=draft-1");
  });
});
