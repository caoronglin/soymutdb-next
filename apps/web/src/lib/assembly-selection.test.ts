import { describe, expect, it } from "vitest";

import { assemblyOptionLabel, resolveAssemblyParam } from "./assembly-selection";

const V4 = { id: 4, name: "Wm82", version: "a4.v1", species: "Glycine max", is_default: false } as never;
const V5 = { id: 5, name: "Wm82", version: "a5", species: "Glycine max", is_default: true } as never;
const ZH13 = { id: 6, name: "ZH13", version: "v1", species: "Glycine max", is_default: false } as never;

describe("resolveAssemblyParam", () => {
  it("treats an empty parameter as absent", () => {
    expect(resolveAssemblyParam([V4, V5], "")).toEqual({ status: "absent" });
    expect(resolveAssemblyParam([V4, V5], null)).toEqual({ status: "absent" });
  });

  it("resolves a stable id before any label", () => {
    const result = resolveAssemblyParam([V4, V5], "5");
    expect(result).toMatchObject({ status: "resolved", via: "id" });
    expect(result.status === "resolved" && result.assembly.version).toBe("a5");
  });

  it("resolves a unique legacy name", () => {
    expect(resolveAssemblyParam([V4, V5, ZH13], "ZH13")).toMatchObject({
      status: "resolved",
      via: "name",
    });
  });

  it("reports a name shared by v4 and v5 as ambiguous instead of collapsing it", () => {
    const result = resolveAssemblyParam([V4, V5], "Wm82");
    expect(result.status).toBe("ambiguous");
    expect(result.status === "ambiguous" && result.matches).toHaveLength(2);
  });

  it("reports an unknown parameter instead of falling back to the default", () => {
    expect(resolveAssemblyParam([V4, V5], "99").status).toBe("unknown");
    expect(resolveAssemblyParam([V4, V5], "Wm82.a9").status).toBe("unknown");
  });
});

describe("assemblyOptionLabel", () => {
  it("always includes the version so two Wm82 rows are distinguishable", () => {
    expect(assemblyOptionLabel(V4)).toBe("Wm82 a4.v1");
    expect(assemblyOptionLabel(V5)).toBe("Wm82 a5");
    expect(assemblyOptionLabel(ZH13)).toBe("ZH13 v1");
  });
});
