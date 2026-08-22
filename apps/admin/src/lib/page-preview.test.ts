import { describe, expect, it } from "vitest";
import type { PageDefinitionV2 } from "@soymutdb/shared";
import { buildPreviewDocument } from "./page-preview";

function definition(): PageDefinitionV2 {
  return {
    schema_version: 2,
    title_key: "nav.home",
    root: {
      type: "columns",
      props: { columns: 1 },
      children: [
        {
          type: "rich_text",
          props: { content: "<p>Hello</p><script>alert(1)</script>" },
        },
      ],
    },
    data_sources: [],
    theme_id: "scientific-dark",
    layouts: {
      desktop: { columns: 12 },
      tablet: { columns: 8 },
      mobile: { columns: 4 },
    },
  };
}

describe("Admin page preview document", () => {
  it("emits a script-free static document with theme and layout metadata", () => {
    const document = buildPreviewDocument(definition());
    expect(document).toContain("data-theme=\"scientific-dark\"");
    expect(document).toContain("data-layouts=");
    expect(document).toContain("&lt;script&gt;");
    expect(document).not.toMatch(/<script\b/i);
  });

  it("never emits raw component prop URLs or handlers", () => {
    const document = buildPreviewDocument({
      ...definition(),
      root: {
        type: "link",
        props: { href: "javascript:alert(1)", onclick: "alert(1)" },
      },
    });
    expect(document).not.toContain("javascript:");
    expect(document).not.toContain("onclick");
  });
});
