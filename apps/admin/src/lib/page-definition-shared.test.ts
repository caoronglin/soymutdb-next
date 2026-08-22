import { describe, expect, it } from "vitest";
import { normalizePageDefinition } from "@soymutdb/shared";

describe("shared PageDefinition compatibility", () => {
  it("upgrades a v1 editor payload before it is edited or saved", () => {
    const root = { type: "columns" as const, props: {}, children: [] };
    expect(normalizePageDefinition({ root })).toEqual({
      schema_version: 2,
      root,
      data_sources: [],
      theme_id: "scientific-light",
      layouts: { desktop: {}, tablet: {}, mobile: {} },
    });
  });
});
