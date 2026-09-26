import { defineComponent, h } from "vue";
import { describe, expect, it } from "vitest";
import { listTrackRenderers, registerTrackRenderer, resolveTrackRenderer } from "./registry";

const DummyRenderer = defineComponent({
  name: "DummyRenderer",
  setup() {
    return () => h("div");
  },
});

describe("track renderer registry", () => {
  it("registers and resolves a descriptor", () => {
    registerTrackRenderer("TestVariantTrack", { component: DummyRenderer });
    expect(resolveTrackRenderer("TestVariantTrack")?.component).toBe(DummyRenderer);
  });

  it("keeps the optional capability on the descriptor", () => {
    registerTrackRenderer("TestAlignmentTrack", {
      component: DummyRenderer,
      requiredCapability: "alignment",
    });
    expect(resolveTrackRenderer("TestAlignmentTrack")?.requiredCapability).toBe("alignment");
  });

  it("throws on a duplicate type", () => {
    registerTrackRenderer("TestDuplicateTrack", { component: DummyRenderer });
    expect(() =>
      registerTrackRenderer("TestDuplicateTrack", { component: DummyRenderer }),
    ).toThrow(/duplicate/i);
  });

  it("throws on an empty type", () => {
    expect(() => registerTrackRenderer("", { component: DummyRenderer })).toThrow(
      /non-empty/i,
    );
  });

  it("returns undefined for an unknown type", () => {
    expect(resolveTrackRenderer("TestNeverRegisteredTrack")).toBeUndefined();
  });

  it("lists registered types in registration order", () => {
    const before = listTrackRenderers().length;
    registerTrackRenderer("TestListA", { component: DummyRenderer });
    registerTrackRenderer("TestListB", { component: DummyRenderer });
    const types = listTrackRenderers();
    expect(types.length).toBe(before + 2);
    expect(types).toContain("TestListA");
    expect(types.indexOf("TestListA")).toBeLessThan(types.indexOf("TestListB"));
  });
});
