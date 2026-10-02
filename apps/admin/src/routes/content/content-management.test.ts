// FUNCTIONAL — content management URL state is the only source of truth.
//
// Contract under test (docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md:119-120,
// docs/3.9升级优化文档.md §3 "URL 为真源"): the content-management table is derived from the
// query string, not from component state. A shared link, a refresh and the browser Back button
// must all reproduce the same result set, and a malformed parameter must fall back to a defined
// default instead of rendering an empty table or, worse, an unbounded page.
//
// If this is RED: an operator's filtered view is no longer shareable, and a hand-edited URL such
// as `?page=0` or `?status=pending` silently changes which rows are fetched.
import { describe, expect, it } from "vitest";

import { contentKeys } from "./query-keys";
import {
  parseContentPageSearch,
  serializeContentPageSearch,
  type ContentPageSearch,
} from "./search";

describe("parseContentPageSearch", () => {
  it("falls back to the first unfiltered page for an empty query", () => {
    expect(parseContentPageSearch({})).toEqual({
      page: 1,
      status: "all",
      category: "",
      edit: undefined,
    });
  });

  it("keeps a valid operator query intact", () => {
    expect(
      parseContentPageSearch({ page: "3", status: "draft", category: "  help  ", edit: " help " }),
    ).toEqual({ page: 3, status: "draft", category: "help", edit: "help" });
  });

  it("rejects page values that are not positive safe integers", () => {
    // `Number("")` is 0 and `Number("2.5")` is fractional: both must fall back
    // rather than reach the API as a pagination cursor.
    for (const page of ["0", "-1", "2.5", "", "  ", "abc", "1e400", Number.NaN, Infinity]) {
      expect(parseContentPageSearch({ page }).page, String(page)).toBe(1);
    }
  });

  it("coerces a numeric page that arrives as a number", () => {
    expect(parseContentPageSearch({ page: 7 }).page).toBe(7);
  });

  it("treats an unknown status as unfiltered instead of passing it to the API", () => {
    for (const status of ["pending", "PUBLISHED", "", 5, null, undefined]) {
      expect(parseContentPageSearch({ status }).status, String(status)).toBe("all");
    }
  });

  it("ignores non-string category values", () => {
    expect(parseContentPageSearch({ category: 42 }).category).toBe("");
  });
});

describe("serializeContentPageSearch", () => {
  it("omits every default so the canonical URL stays short", () => {
    expect(serializeContentPageSearch({ page: 1, status: "all", category: "" })).toEqual({});
  });

  it("writes only the dimensions an operator actually changed", () => {
    expect(
      serializeContentPageSearch({ page: 4, status: "published", category: "news", edit: "news" }),
    ).toEqual({ page: 4, status: "published", category: "news", edit: "news" });
  });

  it("round-trips a query without losing or inventing a filter", () => {
    const searches: ContentPageSearch[] = [
      { page: 1, status: "all", category: "" },
      { page: 2, status: "archived", category: "guide" },
      { page: 9, status: "draft", category: "  notice ", edit: " notice " },
    ];
    for (const search of searches) {
      expect(parseContentPageSearch(serializeContentPageSearch(search)), search.label).toEqual({
        ...search,
        category: search.category.trim(),
        edit: search.edit?.trim(),
      });
    }
  });
});

describe("contentKeys", () => {
  it("separates every page/status/category combination", () => {
    const base = { page: 1, status: "all", category: "" };
    const first = contentKeys.pages(base);
    expect(contentKeys.pages({ ...base, page: 2 })).not.toEqual(first);
    expect(contentKeys.pages({ ...base, status: "draft" })).not.toEqual(first);
    expect(contentKeys.pages({ ...base, category: "help" })).not.toEqual(first);
  });

  it("keeps a page detail cache from being served for the list it belongs to", () => {
    const list = contentKeys.pages({ page: 1, status: "all", category: "" });
    const versions = contentKeys.pageVersions("page-1");
    expect(versions).not.toEqual(list);
    expect(versions.slice(0, contentKeys.all.length)).toEqual([...contentKeys.all]);
  });

  it("gives two different pages different version caches", () => {
    expect(contentKeys.pageVersions("page-1")).not.toEqual(contentKeys.pageVersions("page-2"));
  });
});