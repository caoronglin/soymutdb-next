import { describe, expect, it } from "vitest";
import { contentKeys } from "./query-keys";

describe("contentKeys", () => {
  it("scopes list and version keys under the pages invalidation root", () => {
    const listKey = contentKeys.pages({ page: 3, status: "published", category: "guide" });
    const versionKey = contentKeys.pageVersions("page-1");

    expect(listKey).toEqual(["admin-pages", 3, "published", "guide"]);
    expect(versionKey).toEqual(["admin-pages", "page-1", "versions"]);
    expect(listKey).toEqual(expect.arrayContaining([...contentKeys.all]));
    expect(versionKey).toEqual(expect.arrayContaining([...contentKeys.all]));
  });
});
