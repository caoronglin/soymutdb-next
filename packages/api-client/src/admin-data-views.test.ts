import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildSourceFilters,
  createAdminDataView,
  deleteAdminDataView,
  fetchDataViewRows,
  listAdminDataViews,
  listDataViewSources,
  updateAdminDataView,
  type AdminDataView,
} from "./admin-data-views";

const VIEW: AdminDataView = {
  id: 4,
  name: "High-impact variants",
  source: "variants",
  view_type: "grid",
  visible_fields: ["variant_id", "impact"],
  // 0059 made both fields required on the response type: \`searchable_fields\`
  // is the search-box allowlist (empty = no search box) and \`visibility\`
  // decides whether the saved view is advertised in the picker.
  searchable_fields: ["variant_id"],
  visibility: "visible",
  filters: { impact: "HIGH", start: " 100 " },
  sort_field: "position",
  sort_dir: "desc",
  group_field: null,
  title_field: null,
  page_size: 25,
  is_default: false,
  notes: null,
  created_at: "2026-11-09T00:00:00Z",
  updated_at: "2026-11-09T00:00:00Z",
};

describe("saved data view client contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("builds numeric filters and drops blank values", () => {
    expect(
      buildSourceFilters({
        source: "variants",
        filters: { impact: "HIGH", start: " 100 ", ref: " " },
      }),
    ).toEqual({ impact: "HIGH", start: 100 });
  });

  it("pages genes server-side with the saved sort", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          page: 1,
          page_size: 25,
          total: 0,
          total_pages: 0,
          next_cursor: null,
          has_more: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    await fetchDataViewRows(
      {
        ...VIEW,
        source: "genes",
        filters: { chromosome: "Gm01", start_pos: "100", end_pos: "200" },
        sort_field: "gene_id",
        sort_dir: "asc",
      },
      { page: 2 },
    );

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("chromosome")).toBe("Gm01");
    expect(parsed.searchParams.get("start_pos")).toBe("100");
    expect(parsed.searchParams.get("end_pos")).toBe("200");
    expect(parsed.searchParams.get("page")).toBe("2");
    expect(parsed.searchParams.get("page_size")).toBe("25");
    expect(parsed.searchParams.get("sort_by")).toBe("gene_id");
    expect(parsed.searchParams.get("sort_dir")).toBe("asc");
  });

  it("follows the variant cursor and keeps the public filter names", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [{ variant_id: "v1", position: 20 }, { variant_id: "v2", position: 10 }],
          cursor: null,
          next_cursor: "next",
          has_more: true,
          total_count: null,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const page = await fetchDataViewRows(VIEW, { cursor: "c1" });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("cursor")).toBe("c1");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.get("impact")).toBe("HIGH");
    expect(parsed.searchParams.get("start")).toBe("100");
    // Sorting over a cursor page is applied to the rows that arrived.
    expect(page.items.map((row) => row.position)).toEqual([20, 10]);
    expect(page.nextCursor).toBe("next");
    expect(page.hasMore).toBe(true);
  });

  it("uses offset paging for mutant lines and reports no server total", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ public_id: "SM7K3ZQ9P2AX" }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const page = await fetchDataViewRows(
      { ...VIEW, source: "mutant_lines", filters: { q: "soy" }, page_size: 5, sort_field: null, sort_dir: null },
      { page: 3 },
    );

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("offset")).toBe("10");
    expect(parsed.searchParams.get("limit")).toBe("5");
    expect(parsed.searchParams.get("q")).toBe("soy");
    expect(page.total).toBeNull();
    expect(page.items).toHaveLength(1);
  });
});

describe("admin data view endpoints", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads the source vocabulary", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [{ source: "genes", fields: [], filter_fields: [], default_fields: [] }] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await listDataViewSources();

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toMatch(/\/admin\/data-views\/sources$/);
  });

  it("scopes the list to one source", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await listAdminDataViews({ source: "genes" });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").searchParams.get("source")).toBe("genes");
  });

  it("writes, patches by id and deletes", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(VIEW), { status: 201, headers: { "content-type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(VIEW), { status: 200, headers: { "content-type": "application/json" } }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await createAdminDataView({
      name: VIEW.name,
      source: "variants",
      visible_fields: VIEW.visible_fields,
    });
    await updateAdminDataView(4, { is_default: true });
    await deleteAdminDataView(4);

    const calls = fetchMock.mock.calls.map(([url, init]) => ({
      url: new URL(String(url), "http://localhost").pathname,
      method: (init as RequestInit | undefined)?.method,
    }));
    expect(calls[0].url).toMatch(/\/admin\/data-views$/);
    expect(calls[0].method).toBe("POST");
    expect(calls[1].url).toMatch(/\/admin\/data-views\/4$/);
    expect(calls[1].method).toBe("PUT");
    expect(calls[2].url).toMatch(/\/admin\/data-views\/4$/);
    expect(calls[2].method).toBe("DELETE");
  });
});