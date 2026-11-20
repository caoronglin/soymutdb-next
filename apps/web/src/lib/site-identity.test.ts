import { describe, expect, it } from "vitest";

import { brandWordmarkParts, databaseKindLabelKey } from "./site-identity";

describe("admin-owned site identity", () => {
  it("keeps the gradient accent for the default SoyMutDB wordmark", () => {
    expect(brandWordmarkParts("SoyMutDB")).toEqual({
      before: "Soy",
      accent: "Mut",
      after: "DB",
    });
  });

  it("renders a custom brand name unchanged", () => {
    expect(brandWordmarkParts("大豆突变数据库")).toEqual({
      before: "大豆突变数据库",
      accent: null,
      after: "",
    });
  });

  it("adds a profile badge only for non-genome database kinds", () => {
    expect(databaseKindLabelKey("genome")).toBeNull();
    expect(databaseKindLabelKey("gene_ontology")).toBe("site.databaseKind.gene_ontology");
    expect(databaseKindLabelKey("transcription_factor")).toBe(
      "site.databaseKind.transcription_factor",
    );
  });
});