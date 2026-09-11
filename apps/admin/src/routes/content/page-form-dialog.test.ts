import { describe, expect, it } from "vitest";
import { initPageFormValues } from "./page-form-dialog";

describe("initPageFormValues", () => {
  it("normalizes optional legacy page values for an edit form", () => {
    expect(initPageFormValues({
      id: "page-1", slug: "guide", title_en: "Guide", title_zh: null,
      content_en: "English", content_zh: null, summary: null, category: null,
      status: "archived", sort_order: 4, author_name: null, published_at: null,
      current_version: 2, created_at: "2026-01-01", updated_at: "2026-01-02",
    })).toMatchObject({
      slug: "guide", title_zh: "", content_zh: "", summary: "", category: "",
      sort_order: "4", status: "draft",
    });
  });
});
