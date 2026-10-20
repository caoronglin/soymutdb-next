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

  it("rejects duplicate legacy names rather than taking the first match", () => {
    const versions = [
      { id: 4, name: "Wm82", version: "v4", is_default: false },
      { id: 5, name: "Wm82", version: "v5", is_default: true },
    ];
    expect(resolveSearchAssembly(versions, "Wm82")).toBeUndefined();
    expect(resolveSearchAssembly(versions, "5")?.version).toBe("v5");
    expect(resolveSearchAssembly(versions, " 4 ")?.version).toBe("v4");
  });

  it("prefers a stable id over another assembly's numeric-looking name", () => {
    const versions = [{ id: 4, name: "5" }, { id: 5, name: "Wm82" }];
    expect(resolveSearchAssembly(versions, "5")?.id).toBe(5);
  });

  it("waits for assemblies to load without guessing a genome", () => {
    expect(resolveSearchAssembly(undefined, "v4")).toBeUndefined();
    expect(resolveSearchAssembly([])).toBeUndefined();
  });
});
