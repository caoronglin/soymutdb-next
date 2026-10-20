import { describe, expect, it } from "vitest";
import { Route } from "./blast";

describe("legacy BLAST route", () => {
  it("redirects before rendering and replaces the legacy history entry", () => {
    const beforeLoad = Route.options.beforeLoad;
    expect(beforeLoad).toBeTypeOf("function");
    try {
      (beforeLoad as () => never)();
      throw new Error("expected a router redirect");
    } catch (error) {
      expect(error).toMatchObject({ options: { to: "/blast", replace: true } });
    }
    expect(Route.options.component).toBeUndefined();
  });
});
