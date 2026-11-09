import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@soymutdb/api-client";
import { usePublishedPageDefinition, usePublishedPageRoutes } from "./page-definitions";

const mocks = vi.hoisted(() => ({
  getPageDefinition: vi.fn(),
  listPublishedPageDefinitions: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getPageDefinition: mocks.getPageDefinition,
    listPublishedPageDefinitions: mocks.listPublishedPageDefinitions,
  };
});

vi.mock("./site-variant", () => ({ SITE_VARIANT: "external" }));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mocks.getPageDefinition.mockReset();
  mocks.listPublishedPageDefinitions.mockReset();
});

describe("usePublishedPageDefinition", () => {
  it("returns null when the route has no published definition", async () => {
    mocks.getPageDefinition.mockRejectedValue(new ApiError("not found", 404));
    const { result } = renderHook(() => usePublishedPageDefinition("/about"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it("normalises a stored v1 definition to the current contract", async () => {
    mocks.getPageDefinition.mockResolvedValue({
      route: "/about",
      version: 3,
      status: "published",
      definition: { root: { type: "notice", props: { content: "hello" } } },
    });
    const { result } = renderHook(() => usePublishedPageDefinition("/about"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toMatchObject({
      schema_version: 2,
      theme_id: "scientific-light",
      data_sources: [],
      root: { type: "notice", props: { content: "hello" } },
    });
  });

  it("surfaces non-404 failures instead of silently falling back", async () => {
    mocks.getPageDefinition.mockRejectedValue(new ApiError("boom", 500));
    const { result } = renderHook(() => usePublishedPageDefinition("/about"), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe("usePublishedPageRoutes", () => {
  it("treats a disabled feature (404) as an empty route list", async () => {
    mocks.listPublishedPageDefinitions.mockRejectedValue(new ApiError("disabled", 404));
    const { result } = renderHook(() => usePublishedPageRoutes(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});