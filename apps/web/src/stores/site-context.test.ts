import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { getReleaseId } from "@soymutdb/api-client";

import { useSiteContextStore } from "./site-context";

describe("site context store (DB-CORE-5/6)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps the displayed release and the request header release identical", () => {
    const store = useSiteContextStore();
    store.setRelease("2026.10");
    expect(store.releaseId).toBe("2026.10");
    // The api-client sends this exact value as X-SoyMutDB-Release.
    expect(getReleaseId()).toBe("2026.10");
    store.setRelease(null);
    expect(store.releaseId).toBeNull();
    expect(getReleaseId()).toBeNull();
  });

  it("exposes the build-time site variant without runtime inference", () => {
    const store = useSiteContextStore();
    expect(["external", "internal"]).toContain(store.siteVariant);
    expect(store.isInternal).toBe(store.siteVariant === "internal");
  });
});
