import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const helpSource = readFileSync(new URL("../help.tsx", import.meta.url), "utf8");

describe("Help page publication claims", () => {
  it("does not publish unverified citation or release commitments", () => {
    expect(helpSource).not.toContain("10.1111/pbi.70000");
    expect(helpSource).not.toContain("Major releases occur twice a year");
    expect(helpSource).not.toContain("current release is v2.0");
  });

  it("does not advertise an unavailable GraphQL API", () => {
    expect(helpSource).not.toContain("GraphQL schema");
    expect(helpSource).toContain("REST API v1 reference");
  });
});
