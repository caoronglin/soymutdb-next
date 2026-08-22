import { describe, expect, it } from "vitest";
import { normalizePageDefinition } from "@soymutdb/shared";

const ROOT = { type: "columns" as const, props: { columns: 1 }, children: [] };

describe("PageDefinition v2 compatibility", () => {
  it("normalizes a v1 definition to safe v2 defaults", () => {
    expect(normalizePageDefinition({ title_key: "nav.home", root: ROOT })).toEqual({
      schema_version: 2,
      title_key: "nav.home",
      root: ROOT,
      data_sources: [],
      theme_id: "scientific-light",
      layouts: { desktop: {}, tablet: {}, mobile: {} },
    });
  });

  it("preserves valid v2 metadata", () => {
    const definition = {
      schema_version: 2 as const,
      root: ROOT,
      data_sources: [
        { id: "genes", kind: "dataset", dataset_version_id: "dataset-v7", config: { limit: 20 } },
      ],
      theme_id: "compact-data" as const,
      layouts: {
        desktop: { columns: 12 },
        tablet: { columns: 8 },
        mobile: { columns: 4 },
      },
    };

    expect(normalizePageDefinition(definition)).toEqual(definition);
  });

  it("rejects unsupported schema versions", () => {
    expect(normalizePageDefinition({ schema_version: 3, root: ROOT })).toBeNull();
  });
});
