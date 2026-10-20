import { describe, expect, it } from "vitest";

import {
  isReleaseStatus,
  readActiveReleaseId,
  statusTone,
  toReleaseRow,
  toReleaseRows,
} from "./release-rows";

/**
 * The payload shape is copied from `apps/api/app/schemas/content.py::ReleaseResponse`
 * as `_to_response()` in `apps/api/app/api/v1/releases.py` serialises it. If the
 * API changes, these fixtures are what should fail first — that is the point:
 * the page used to be typed against `ReleaseSummary`, which advertises four
 * fields this endpoint never sends, so no compiler or test noticed.
 */
const PUBLISHED = {
  id: "7",
  version: "v5.0.0",
  name: "Glycine max v5",
  description: "Soybean reference 5",
  variant_count: 1234,
  gene_count: 56,
  mutant_line_count: 7,
  status: "published",
  published_at: "2026-10-02T08:30:00Z",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-10-02T08:30:00Z",
};

const DRAFT = {
  id: "3",
  version: "v5.1.0-rc1",
  name: "Glycine max v5.1 rc",
  description: null,
  variant_count: 10,
  gene_count: 1,
  mutant_line_count: 0,
  status: "draft",
  published_at: null,
  created_at: "2026-10-10T00:00:00Z",
  updated_at: "2026-10-10T00:00:00Z",
};

describe("release row mapping", () => {
  it("maps the fields the API actually returns", () => {
    const [row] = toReleaseRows([PUBLISHED]);
    expect(row).toEqual({
      id: "7",
      version: "v5.0.0",
      name: "Glycine max v5",
      description: "Soybean reference 5",
      status: "published",
      variantCount: 1234,
      geneCount: 56,
      mutantLineCount: 7,
      publishedAt: "2026-10-02T08:30:00Z",
      createdAt: "2026-09-01T00:00:00Z",
      updatedAt: "2026-10-02T08:30:00Z",
      isActive: false,
    });
  });

  it("keeps a null publish date and a null description instead of coercing them", () => {
    const [row] = toReleaseRows([DRAFT]);
    expect(row.publishedAt).toBeNull();
    expect(row.description).toBeNull();
  });

  it("derives the active row from /releases/active, not from a list field", () => {
    // `is_active` is what the old page read, and the API never sends it. A
    // payload that happens to carry it must not resurrect the badge.
    const payload = [{ ...PUBLISHED, is_active: true }];
    expect(toReleaseRows(payload)[0].isActive).toBe(false);
    expect(toReleaseRows(payload, "7")[0].isActive).toBe(true);
    expect(toReleaseRows(payload, "3")[0].isActive).toBe(false);
  });

  it("drops entries the table could not key, and non-array payloads", () => {
    expect(toReleaseRows([{ version: "v1" }, null, "7", PUBLISHED]).map((row) => row.id)).toEqual(["7"]);
    expect(toReleaseRows({ detail: "nope" })).toEqual([]);
    expect(toReleaseRows(undefined)).toEqual([]);
  });

  it("coerces counts and timestamps instead of rendering NaN", () => {
    const [row] = toReleaseRows([
      { id: "9", variant_count: -3, gene_count: "many", mutant_line_count: null, published_at: "not-a-date" },
    ]);
    expect(row.variantCount).toBe(0);
    expect(row.geneCount).toBe(0);
    expect(row.mutantLineCount).toBe(0);
    expect(row.publishedAt).toBeNull();
  });

  it("accepts a numeric id, the way ReleaseResponse str() would produce a string", () => {
    expect(toReleaseRow({ id: 7 })?.id).toBe("7");
    expect(toReleaseRow({ id: null })).toBeNull();
    expect(toReleaseRow(undefined)).toBeNull();
  });

  it("passes an unrecognised status through instead of coercing it to draft", () => {
    const [row] = toReleaseRows([{ id: "1", status: "quarantined" }]);
    expect(row.status).toBe("quarantined");
    expect(statusTone(row.status)).toBe("default");
  });
});

describe("release status vocabulary", () => {
  it("matches the backend enum and nothing else", () => {
    expect(isReleaseStatus("published")).toBe(true);
    expect(isReleaseStatus("rolled_back")).toBe(true);
    expect(isReleaseStatus("active")).toBe(false);
    expect(isReleaseStatus(undefined)).toBe(false);
  });

  it("keeps the previous tag tones", () => {
    expect(statusTone("published")).toBe("green");
    expect(statusTone("ready")).toBe("blue");
    expect(statusTone("validated")).toBe("blue");
    expect(statusTone("rolled_back")).toBe("orange");
    expect(statusTone("draft")).toBe("default");
  });
});

describe("active release pointer", () => {
  it("reads release_id from /releases/active", () => {
    expect(readActiveReleaseId({ release_id: "7", version: "v5.0.0", published_at: "2026-10-02T08:30:00Z" })).toBe("7");
    expect(readActiveReleaseId({ release_id: 7 })).toBe("7");
  });

  it("treats a pointer with null fields (before the first publish) as an answer, not an error", () => {
    expect(readActiveReleaseId({ release_id: null, version: null, published_at: null })).toBeNull();
    expect(readActiveReleaseId(undefined)).toBeNull();
    expect(readActiveReleaseId([{ release_id: "7" }])).toBeNull();
  });
});
