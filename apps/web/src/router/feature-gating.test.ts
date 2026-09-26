import { describe, expect, it } from "vitest";

import { isFeatureGated, JBROWSE_COMPONENT_KEYS } from "./feature-gating";

describe("portal feature gating (core-only deployment)", () => {
  it("gates both JBrowse component keys, including the search-gbrowse route", () => {
    // The route is named `search-gbrowse` but its component key is `gbrowse`;
    // a name-based check missed it.
    expect(JBROWSE_COMPONENT_KEYS.has("browser")).toBe(true);
    expect(JBROWSE_COMPONENT_KEYS.has("gbrowse")).toBe(true);
    expect(isFeatureGated("gbrowse", false)).toBe(true);
    expect(isFeatureGated("browser", false)).toBe(true);
  });

  it("keeps JBrowse routes when the service is enabled", () => {
    expect(isFeatureGated("gbrowse", true)).toBe(false);
    expect(isFeatureGated("browser", true)).toBe(false);
  });

  it("never gates unrelated routes", () => {
    for (const key of ["search-genes", "search-location", "genes", "variants"]) {
      expect(isFeatureGated(key, false)).toBe(false);
    }
  });
});
