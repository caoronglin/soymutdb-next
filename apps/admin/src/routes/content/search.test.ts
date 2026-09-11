import { describe, expect, it } from "vitest";
import { parseContentPageSearch, serializeContentPageSearch } from "./search";

describe("content page search", () => {
  it("normalizes untrusted URL values to backward-compatible defaults", () => {
    expect(parseContentPageSearch({ page: "0", status: "unknown", category: 4 })).toEqual({
      page: 1, status: "all", category: "",
    });
  });
  it("serializes only non-default page filters", () => {
    expect(serializeContentPageSearch({ page: 3, status: "published", category: " guide " })).toEqual({
      page: 3, status: "published", category: " guide ",
    });
    expect(serializeContentPageSearch({ page: 1, status: "all", category: "" })).toEqual({});
  });
});
