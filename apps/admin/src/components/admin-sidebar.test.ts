import { describe, expect, it } from "vitest";
import { NAV_SECTIONS } from "./admin-sidebar";

describe("Admin content navigation", () => {
  it("groups content records under stable route entry points", () => {
    const content = NAV_SECTIONS.find((section) => section.label === "Content");
    expect(content?.items.map((item) => item.path)).toEqual([
      "/content/pages",
      "/content/legacy",
      "/news",
      "/publications",
      "/media",
    ]);
  });

  it("keeps Page Builder editing routes out of the presentation list", () => {
    const presentation = NAV_SECTIONS.find((section) => section.label === "Presentation");
    expect(presentation?.items.some((item) => item.path === "/page-builder")).toBe(false);
  });
});
