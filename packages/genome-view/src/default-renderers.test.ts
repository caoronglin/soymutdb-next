import { describe, expect, it } from "vitest";

import { registerDefaultTrackRenderers } from "./default-renderers";
import { resolveTrackRenderer } from "./registry";

describe("registerDefaultTrackRenderers", () => {
  it("binds the supported backend track types", () => {
    registerDefaultTrackRenderers();
    for (const type of ["ReferenceSequenceTrack", "FeatureTrack", "VariantTrack", "QuantitativeTrack"]) {
      expect(resolveTrackRenderer(type)?.component).toBeDefined();
    }
  });

  it("is idempotent", () => {
    expect(() => {
      registerDefaultTrackRenderers();
      registerDefaultTrackRenderers();
    }).not.toThrow();
  });
});
