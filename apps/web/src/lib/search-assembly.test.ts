import { describe, expect, it } from "vitest";
import { resolveSearchAssembly } from "./search-assembly";

const assemblies = [
  { id: 4, name: "v4", is_default: false },
  { id: 5, name: "v5", is_default: true },
];

describe("assembly-scoped search", () => {
  it("selects an explicit id or name before the configured default", () => {
    expect(resolveSearchAssembly(assemblies, "4")?.name).toBe("v4");
    expect(resolveSearchAssembly(assemblies, "v4")?.id).toBe(4);
    expect(resolveSearchAssembly(assemblies)?.name).toBe("v5");
  });

  it("rejects an invalid deep-link assembly instead of querying a different genome", () => {
    const selected = resolveSearchAssembly(assemblies, "unknown");
    // Single-factor ablation: replacing the explicit-match guard with a fallback
    // incorrectly runs this same input against the default v5 namespace.
    const withoutGuard = selected ?? assemblies.find((assembly) => assembly.is_default);
    expect(selected).toBeUndefined();
    expect(withoutGuard?.name).toBe("v5");
  });

  it("waits for assemblies to load without guessing a genome", () => {
    expect(resolveSearchAssembly(undefined, "v4")).toBeUndefined();
    expect(resolveSearchAssembly([])).toBeUndefined();
  });
});
